"""Réseaux : appareils sanitaires, éclairage, prises, climatisation, plomberie, plans et quantités."""
import math

import ezdxf
import pytest

from baticalc.importers import import_plan
from baticalc.mep.design import _dn_pressure, _simultaneity, design_mep, load_params
from baticalc.mep.drawings import write_mep_drawings
from baticalc.mep.fixtures import estimate_from_room
from baticalc.project import Project
from baticalc.recognition import build_model

CM = 100.0


def _poly(msp, pts, layer, close=True):
    msp.add_lwpolyline([(x * CM, y * CM) for x, y in pts], close=close, dxfattribs={"layer": layer})


def _line(msp, a, b, layer):
    msp.add_line((a[0] * CM, a[1] * CM), (b[0] * CM, b[1] * CM), dxfattribs={"layer": layer})


def _text(msp, x, y, txt):
    msp.add_mtext(txt, dxfattribs={"layer": "AR_TEXTES", "insert": (x * CM, y * CM), "char_height": 15})


def write_sanitary_dxf(path):
    """Plan 12 × 8 m : un bureau, un bloc sanitaire (2 cabines W.C + toilettes), une cuisine."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5
    for n in ("A-MURS", "POTEAUX", "AR_TEXTES"):
        doc.layers.add(n)
    msp = doc.modelspace()
    _poly(msp, [(-0.2, -0.2), (12.2, -0.2), (12.2, 8.2), (-0.2, 8.2)], "A-MURS")
    _poly(msp, [(0, 0), (12, 0), (12, 8), (0, 8)], "A-MURS")
    for x in (7.95, 8.05):                       # cloison x = 8, porte 3,5–4,4
        _line(msp, (x, 0), (x, 3.5), "A-MURS")
        _line(msp, (x, 4.4), (x, 8), "A-MURS")
    for y in (3.95, 4.05):                       # cloison y = 4 côté est
        _line(msp, (8.05, y), (12, y), "A-MURS")
    for x in (0, 4, 8, 12):
        for y in (0, 4, 8):
            pts = [(x - .125, y - .125), (x + .125, y - .125), (x + .125, y + .125), (x - .125, y + .125)]
            _poly(msp, pts, "POTEAUX")
            h = msp.add_hatch(dxfattribs={"layer": "POTEAUX"})
            h.paths.add_polyline_path([(a * CM, b * CM) for a, b in pts], is_closed=True)
    _text(msp, 3.0, 4.0, "Bureau 60.00m²")
    _text(msp, 9.0, 6.5, "Toilettes 14.00m²")
    _text(msp, 9.0, 5.2, "W.C")
    _text(msp, 10.5, 5.2, "W.C")
    _text(msp, 9.5, 2.0, "Cuisine 15.00m²")
    doc.saveas(path)
    return path


@pytest.fixture
def project(tmp_path):
    bld = build_model(import_plan(write_sanitary_dxf(tmp_path / "sani.dxf")), n_levels=3, floor_height=3.0)
    return Project.from_building(bld)


def test_simultaneity_and_diameters():
    assert _simultaneity(1) == 1.0
    assert _simultaneity(5) == pytest.approx(0.8 / 2)
    dn, v = _dn_pressure(0.3, 2.0)
    assert v <= 2.0 and dn >= 20
    assert _dn_pressure(2.0, 2.0)[0] > dn


def test_estimate_from_room_names():
    assert estimate_from_room({"name": "SDB", "area": 5}) == ["wc", "lavabo", "douche"]
    assert estimate_from_room({"name": "Cuisine", "area": 12}) == ["evier"]
    out = estimate_from_room({"name": "Toilettes Hommes", "area": 10})
    assert out.count("wc") == 4 and "urinoir" in out


def test_fixtures_from_labels(project):
    fx = project.storeys[0].plan.fixtures
    kinds = [f["type"] for f in fx]
    # deux cabines « W.C » étiquetées : les toilettes n'ajoutent que des lavabos
    assert kinds.count("wc") == 2
    assert "lavabo" in kinds and "evier" in kinds


def test_mep_design(project):
    P = load_params()
    mep = design_mep(project, P)
    assert len(mep.storeys) == 1 and "× 3" in mep.storeys[0].name
    sm = mep.storeys[0]
    # éclairage du bureau : n = ceil(E·A / (flux · facteur))
    office = next(r for r in sm.rooms if r["local"].startswith("Bureau"))
    u = P["usages"]["Bureaux"]
    lt = P["luminaires"][u["luminaire"]]
    expect = math.ceil(u["eclairement"] * office["surface"] / (lt["flux_lm"] * P["electricite"]["facteur_utilisation_maintenance"]))
    assert office["luminaires"] == expect
    assert sm.lights and sm.sockets and sm.switches
    assert sm.units and sm.cool_kw > 0
    assert sm.power_kw > 0 and sm.current_a > 0 and sm.feeder["section_mm2"] >= 6
    assert sm.feeder["chute_tension"] <= 3.0
    # plomberie : un groupe, une colonne montante sur 3 niveaux
    assert sm.groups and mep.columns
    assert all(s["dn"] >= 20 for c in mep.columns for s in c["segments"])
    assert mep.tgbt["puissance_kva"] > 0
    q = mep.quantities
    assert any(k.startswith("EL-") for k in q) and any(k.startswith("PL-") for k in q) \
        and any(k.startswith("CL-") for k in q)
    # niveau répété : les quantités sont multipliées par le nombre de niveaux
    n_lum = sum(v[0] for k, v in q.items() if k in ("EL-LGR", "EL-LHU", "EL-LPF", "EL-LRE", "EL-LLE", "EL-LSP"))
    assert n_lum == pytest.approx(3 * len(sm.lights))


def test_mep_drawings(project, tmp_path):
    mep = design_mep(project)
    paths = write_mep_drawings(project, mep, tmp_path)
    assert [p.name for p in paths] == ["reseau_plomberie.dxf", "reseau_electricite.dxf", "reseau_climatisation.dxf"]
    doc = ezdxf.readfile(paths[1])
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"EL-ECL", "EL-PC", "EL-TD", "SCHEMA"} <= layers
    texts = " ".join(e.dxf.text for e in ezdxf.readfile(paths[0]).modelspace().query("TEXT"))
    assert "SCHÉMA DES COLONNES" in texts and "EF Ø" in texts


def test_column_crosses_repeated_levels(project):
    mep = design_mep(project)
    col = mep.columns[0]
    assert len(col["segments"]) == 3
    n = [s["appareils"] for s in col["segments"]]
    assert n[0] == 3 * n[2] and n[1] == 2 * n[2]
    assert col["segments"][0]["dn"] >= col["segments"][2]["dn"]


def test_mep_in_devis(project):
    from baticalc.codes import get_code
    from baticalc.costing.devis import build_devis
    from baticalc.costing.metre import DevisSettings
    from baticalc.design import run
    from baticalc.model import LoadSettings

    res = run(project.storeys[0].plan, LoadSettings(), get_code("bael"))
    mep = design_mep(project)
    dv = build_devis(res, None, DevisSettings(), mep=mep)
    lots = {lot.upper() for lot, _ in dv.lots()}
    assert any("PLOMBERIE" in lot for lot in lots)
    assert any("ELECTRICIT" in lot or "ÉLECTRICIT" in lot for lot in lots)
    assert any("CLIMATISATION" in lot for lot in lots)
    fosse = [ln for ln in dv.lines if "fosse" in ln.designation.lower()]
    assert fosse and "usagers" in fosse[0].designation and "{usagers}" not in fosse[0].designation
