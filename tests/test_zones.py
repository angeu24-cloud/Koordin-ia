"""Locaux : étiquettes, délimitation, catalogue d'usages, trémies, balcons, équilibre."""
import ezdxf
import numpy as np
import pytest

from baticalc.codes import get_code
from baticalc.design import balcony_design, run
from baticalc.importers import import_plan
from baticalc.model import LoadSettings
from baticalc.recognition import build_model
from baticalc.slab import SlabMask
from baticalc.takedown import CONCRETE, compute_takedown, slab_mask
from baticalc.zones import cell_loads, classify, load_catalogue, read_labels, zone_objects

CM = 100.0


def _poly(msp, pts, layer, close=True):
    msp.add_lwpolyline([(x * CM, y * CM) for x, y in pts], close=close, dxfattribs={"layer": layer})


def _line(msp, a, b, layer):
    msp.add_line((a[0] * CM, a[1] * CM), (b[0] * CM, b[1] * CM), dxfattribs={"layer": layer})


def _text(msp, x, y, txt):
    msp.add_mtext(txt, dxfattribs={"layer": "AR_TEXTES", "insert": (x * CM, y * CM), "char_height": 15})


def write_rooms_dxf(path):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5
    for n in ("A-MURS", "POTEAUX", "AR_TEXTES", "GARDE-CORPS"):
        doc.layers.add(n)
    msp = doc.modelspace()
    # façades 10 × 8 m (double trait 20 cm)
    _poly(msp, [(-0.2, -0.2), (10.2, -0.2), (10.2, 8.2), (-0.2, 8.2)], "A-MURS")
    _poly(msp, [(0, 0), (10, 0), (10, 8), (0, 8)], "A-MURS")
    # cloison x = 5 (double trait) avec une porte de 0,9 m entre y = 3,5 et 4,4
    for x in (4.95, 5.05):
        _line(msp, (x, 0), (x, 3.5), "A-MURS")
        _line(msp, (x, 4.4), (x, 8), "A-MURS")
    # poteaux 25 × 25 hachurés
    for x in (0, 5, 10):
        for y in (0, 4, 8):
            pts = [(x - .125, y - .125), (x + .125, y - .125), (x + .125, y + .125), (x - .125, y + .125)]
            _poly(msp, pts, "POTEAUX")
            h = msp.add_hatch(dxfattribs={"layer": "POTEAUX"})
            h.paths.add_polyline_path([(a * CM, b * CM) for a, b in pts], is_closed=True)
    # cage d'ascenseur 1,6 × 1,6 avec la croix conventionnelle
    _poly(msp, [(7, 5), (8.6, 5), (8.6, 6.6), (7, 6.6)], "A-MURS")
    _line(msp, (7, 5), (8.6, 6.6), "A-MURS")
    _line(msp, (7, 6.6), (8.6, 5), "A-MURS")
    # balcon sud de 1,5 m : garde-corps
    _poly(msp, [(1, -0.2), (1, -1.7), (9, -1.7), (9, -0.2)], "GARDE-CORPS", close=False)
    _text(msp, 2.0, 6.0, "Bureau 40.00m²")
    _text(msp, 6.0, 2.0, "Stockage")
    _text(msp, 6.2, 1.6, "38.00m²")          # surface écrite séparément
    _text(msp, 7.5, 5.9, "ASC.")
    _text(msp, 4.0, -1.0, "Balcon 12.00m²")
    doc.saveas(path)
    return path


@pytest.fixture
def rooms(tmp_path):
    return build_model(import_plan(write_rooms_dxf(tmp_path / "locaux.dxf")), n_levels=3, floor_height=3.0)


def test_catalogue():
    cat = load_catalogue()
    assert classify("Balcon", cat).q == 3.5
    assert classify("Local Techn. Plomb. (Bâche à eau)", cat).nom.startswith("Réservoir")
    assert classify("Hall Asc.", cat).nom.startswith("Hall")          # pas une trémie
    assert classify("ASC.", cat).type == "ouverture"
    assert classify("Escalier", cat).g_total == 7.0
    assert classify("Toil. Fem.", cat).q is None                       # même usage que l'étage
    assert classify("Machin", cat) is None
    # règles propres au projet prioritaires
    cat2 = load_catalogue([{"nom": "Salle serveurs", "motifs": ["SERVEUR"], "q": 7.5}])
    assert classify("Salle serveurs", cat2).q == 7.5


def test_labels_with_separate_area(tmp_path):
    d = import_plan(write_rooms_dxf(tmp_path / "l.dxf"))
    labels = {lb.name: lb.area for lb in read_labels(d, load_catalogue())}
    assert labels["Stockage"] == 38.0
    assert labels["Bureau"] == 40.0
    assert labels["ASC."] is None


def test_zones_detected(rooms):
    z = {zz["usage"]: zz for zz in rooms.zones}
    assert set(z) >= {"Bureaux", "Stockage / archives", "Trémie ascenseur", "Balcon / loggia"}
    assert z["Bureaux"]["area"] == pytest.approx(40, rel=0.15)
    assert z["Trémie ascenseur"]["area"] == pytest.approx(1.6 * 1.6, rel=0.25)
    assert z["Balcon / loggia"]["area"] == pytest.approx(12, rel=0.25)
    # le stockage ne déborde pas dans le bureau (porte refermée)
    assert z["Stockage / archives"]["area"] < 45


def test_loads_by_room_and_equilibrium(rooms):
    ls = LoadSettings(continuity=False, degression=False, q_floor=1.5)
    td = compute_takedown(rooms, ls)
    # Q appliqué = somme des q par cellule (trémie retirée, stockage à 5, balcon à 3,5)
    mask = slab_mask(rooms)
    zones = zone_objects(rooms)
    eff, g_w, q_w, _ = cell_loads(mask, zones, td.surface_g_floor, td.surface_q_floor, ls.g_floor, roof=False)
    eff_r, g_r, q_r, _ = cell_loads(mask, zones, td.surface_g_roof, td.surface_q_roof, ls.g_floor, roof=True)
    a = mask.res ** 2
    q_applied = 2 * q_w.sum() * a + q_r.sum() * a
    base = [s for v in td.columns.values() for s in v if s.storey == 1]
    assert sum(s.q for s in base) == pytest.approx(q_applied, rel=1e-6)
    cols = rooms.column_map()
    g_applied = (2 * g_w.sum() + g_r.sum()) * a
    g_applied += 3 * sum(CONCRETE * b.b * b.h * b.length(cols) for b in rooms.beams)
    g_applied += 3 * sum(CONCRETE * c.b * c.h * 3.0 for c in rooms.columns)
    assert sum(s.g for s in base) == pytest.approx(g_applied, rel=1e-6)
    # trémie retirée du plancher
    assert td.slab_area < mask.area - 2.0
    # le stockage charge davantage que le bureau
    assert q_w.max() == 5.0


def test_balcony_console(rooms):
    res = run(rooms, LoadSettings(), get_code("bael"))
    assert res.balconies
    b = res.balconies[0]
    assert 1.2 <= b.length <= 1.8           # porte-à-faux ≈ 1,5 m (au nu de la poutre de rive)
    assert b.h >= max(0.15, b.length / 10)
    # moment d'encastrement : 1,35 (g L²/2 + 1·L) + 1,5 (q L²/2 + 1·1)
    L = b.length
    expect = 1.35 * (b.g * L ** 2 / 2 + 1.0 * L) + 1.5 * (3.5 * L ** 2 / 2 + 1.0)
    assert b.mu == pytest.approx(expect, rel=1e-6)
    assert b.as_top > 0 and b.bars_top.startswith("HA")


def test_balcony_design_long_cantilever():
    b = balcony_design(get_code("ec2"), "P", "Balcon", 10, 2.4, 5.0, 3.5)
    assert b.h >= 0.24 and any("2 m" in n for n in b.notes)


def test_rooms_can_be_disabled(tmp_path):
    bld = build_model(import_plan(write_rooms_dxf(tmp_path / "l.dxf")), rooms=False)
    assert bld.zones == []
