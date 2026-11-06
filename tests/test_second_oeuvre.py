"""Second œuvre : ouvertures, murs par épaisseur, métré des finitions."""
import ezdxf
import pytest

from baticalc.codes import get_code
from baticalc.costing.archi import _wall_classes, archi_metre
from baticalc.costing.metre import DevisSettings
from baticalc.design import run
from baticalc.importers import import_plan
from baticalc.model import LoadSettings
from baticalc.recognition import build_model
from baticalc.slab import SlabMask

K = 100.0


def _line(msp, a, b, layer):
    msp.add_line((a[0] * K, a[1] * K), (b[0] * K, b[1] * K), dxfattribs={"layer": layer})


def write_plan(path):
    """Bâtiment 10 × 8 m : façades de 20 cm, cloison de 10 cm à x = 5 avec une porte,
    une fenêtre de 1,20 m en façade sud, poteaux aux angles et au milieu."""
    from test_zones import write_rooms_dxf

    write_rooms_dxf(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    doc.layers.add("A-FENETRE")
    doc.layers.add("A-PORTE")
    # fenêtre : 3 traits parallèles dans l'épaisseur du mur sud (x de 6,0 à 7,2)
    for y in (-0.15, -0.10, -0.05):
        _line(msp, (6.0, y), (7.2, y), "A-FENETRE")
    # porte de 0,90 m dans la cloison (vantail)
    msp.add_lwpolyline([(4.98 * K, 3.5 * K), (5.02 * K, 3.5 * K), (5.02 * K, 4.4 * K), (4.98 * K, 4.4 * K)],
                       close=True, dxfattribs={"layer": "A-PORTE"})
    doc.saveas(path)
    return path


@pytest.fixture
def bld(tmp_path):
    return build_model(import_plan(write_plan(tmp_path / "p.dxf")), n_levels=2, floor_height=3.0)


def test_openings(bld):
    types = sorted((o["type"], o["facade"], round(o["largeur"], 1)) for o in bld.openings)
    assert ("fenetre", True, 1.2) in types
    assert ("porte", False, 0.9) in types


def test_walls_by_thickness(bld):
    w = _wall_classes(bld, SlabMask.from_dict(bld.footprint or bld.slab))
    # façades 10,4 × 8,4 m au nu extérieur (≈ 36 ml) et cloison de 2 × ~3,5 m
    assert w[20]["total"] == pytest.approx(36, rel=0.15)
    assert w[20]["facade"] == pytest.approx(w[20]["total"], rel=0.15)
    assert w[10]["total"] == pytest.approx(7.4, rel=0.25)


def test_finishes_metre(bld):
    res = run(bld, LoadSettings(), get_code("bael"))
    q = archi_metre(res, DevisSettings())
    h = 3.0 - 0.20
    # maçonnerie de façade : longueur × hauteur nette − fenêtre, sur 2 niveaux
    assert q["MA-A20"].quantity == pytest.approx(2 * (36 * h - 1.2 * 1.2), rel=0.15)
    assert q["ME-FEN"].quantity == 2 and q["ME-APP"].quantity == pytest.approx(2 * 1.2, abs=0.05)
    assert q["ME-PIN"].quantity == pytest.approx(2 * 0.9 * 2.10, rel=0.05)
    # étanchéité = surface de la terrasse ; carrelage + locaux particuliers ≤ emprise
    assert q["ET-ETA"].quantity == pytest.approx(res.takedown.storeys[-1].slab_area)
    fp = SlabMask.from_dict(bld.footprint or bld.slab).area
    assert q["SO-CAR"].quantity <= 2 * fp
    assert q["PE-INT"].quantity > q["EN-INT"].quantity  # murs + plafonds
