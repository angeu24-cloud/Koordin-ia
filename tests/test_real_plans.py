"""Cas inspirés de plans d'architecte réels : planches multiples, calques atypiques,
bâtiment en L, axes en tirets, repères d'axes de l'architecte."""
import shutil

import ezdxf
import pytest

from koordinia.cli import main
from koordinia.codes import get_code
from koordinia.design import run
from koordinia.importers import import_plan
from koordinia.importers.dxf_importer import find_dwg2dxf
from koordinia.model import Building, LoadSettings
from koordinia.recognition import build_model
from koordinia.sheets import crop, find_sheets, select_sheet
from koordinia.takedown import compute_takedown

CM = 100.0  # dessin en centimètres


def _rect(msp, x0, y0, x1, y1, layer, hatch=False):
    pts = [(x0 * CM, y0 * CM), (x1 * CM, y0 * CM), (x1 * CM, y1 * CM), (x0 * CM, y1 * CM)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    if hatch:
        h = msp.add_hatch(dxfattribs={"layer": layer})
        h.paths.add_polyline_path(pts, is_closed=True)


def _sheet(msp, ox, title):
    """Cadre 60 × 40 m (double trait) + cartouche à 2 cases + titre."""
    _rect(msp, ox, 0, ox + 60, 40, "0")
    _rect(msp, ox + 0.3, 0.3, ox + 59.7, 39.7, "0")
    _rect(msp, ox + 40, 0.3, ox + 59.7, 8, "0")    # case de cartouche
    _rect(msp, ox + 48, 0.3, ox + 59.7, 4, "0")
    msp.add_mtext(title, dxfattribs={"layer": "AR_TEXTES", "insert": ((ox + 45) * CM, 6 * CM), "char_height": 30})


def write_architect_dxf(path):
    """Bâtiment en L : rectangle 16 × 10 m auquel on retire le quart haut-gauche 8 × 5 m."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5
    for name in ("A-MURS", "COTATI0N", "AR_TEXTES", "MOBILIER"):
        doc.layers.add(name)
    msp = doc.modelspace()
    _rect(msp, -5, -5, 130, 50, "0")  # cadre général regroupant les planches
    _sheet(msp, 0, "VUE EN PLAN RDC")
    _sheet(msp, 65, "VUE EN PLAN ETAGE COURANT")
    bx, by = 75, 15  # origine du bâtiment dans la planche 2 (m)

    # Murs extérieurs en L (double trait, épaisseur 20 cm), avec une baie de 2,5 m non fermée
    outline = [(0, 0), (16, 0), (16, 10), (8, 10), (8, 5), (0, 5)]
    for off in (0.0, 0.2):
        pts = [(bx + x + (off if x == 0 else -off if x in (16,) else 0), by + y) for x, y in outline]
        msp.add_lwpolyline([(x * CM, y * CM) for x, y in pts], close=True, dxfattribs={"layer": "A-MURS"})
    # une baie : on « efface » visuellement en ajoutant une porte-fenêtre (ligne fine) — le mur reste fermé ici
    # Poteaux 25×25 hachurés sur le calque COTATI0N, trame 4 m
    cols = [(x, y) for x in (0, 4, 8, 12, 16) for y in (0, 5)] + [(x, 10) for x in (8, 12, 16)]
    for x, y in cols:
        _rect(msp, bx + x - 0.125, by + y - 0.125, bx + x + 0.125, by + y + 0.125, "COTATI0N", hatch=True)
    # Axes en tirets sur le calque 0 qui dépassent largement le bâtiment + bulles
    for k, x in enumerate((0, 4, 8, 12, 16)):
        msp.add_line(((bx + x) * CM, (by - 3) * CM), ((bx + x) * CM, (by + 13) * CM),
                     dxfattribs={"layer": "0", "linetype": "CENTER"})
        msp.add_mtext("ABCDE"[k], dxfattribs={"layer": "0", "insert": ((bx + x) * CM, (by + 13.5) * CM),
                                               "char_height": 25})
    for k, y in enumerate((0, 5, 10)):
        msp.add_line(((bx - 3) * CM, (by + y) * CM), ((bx + 19) * CM, (by + y) * CM),
                     dxfattribs={"layer": "0", "linetype": "CENTER"})
        msp.add_mtext(str(k + 1), dxfattribs={"layer": "0", "insert": ((bx - 3.5) * CM, (by + y) * CM),
                                               "char_height": 25})
    # Mobilier dans le vide du L (ne doit pas devenir du plancher)
    _rect(msp, bx + 2, by + 7, bx + 3, by + 8, "MOBILIER")
    doc.saveas(path)
    return path


@pytest.fixture
def plan(tmp_path):
    return write_architect_dxf(tmp_path / "archi.dxf")


def test_sheets_detection(plan):
    sheets = find_sheets(import_plan(plan))
    assert [s.title for s in sheets] == ["VUE EN PLAN RDC", "VUE EN PLAN ETAGE COURANT"]
    assert all(s.is_plan for s in sheets)
    assert select_sheet(sheets, "etage courant").index == 2
    assert select_sheet(sheets, "1").title == "VUE EN PLAN RDC"
    with pytest.raises(ValueError, match="Planches disponibles"):
        select_sheet(sheets, "toiture")


def test_l_shaped_building(plan):
    d = import_plan(plan)
    sheet = select_sheet(find_sheets(d), "etage courant")
    bld = build_model(crop(d, sheet.bbox), n_levels=2)
    assert len(bld.columns) == 13
    assert any("COTATI0N" in w for w in bld.warnings)
    # Surface du L : 16 × 10 − 8 × 5 = 120 m² (au nu extérieur des murs, ± cellules de bord)
    td = compute_takedown(bld, LoadSettings())
    assert td.slab_area == pytest.approx(120, rel=0.04)
    # aucune poutre ne traverse le vide du L (entre (0,5) et (8,10))
    cols = bld.column_map()
    for b in bld.beams:
        c1, c2 = cols[b.start], cols[b.end]
        mx, my = (c1.x + c2.x) / 2, (c1.y + c2.y) / 2
        assert not (mx < 7.9 and my > 5.1), b
    # repères d'axes lus sur le plan
    assert bld.axis_x == ["A", "B", "C", "D", "E"]
    assert bld.axis_y == ["1", "2", "3"]


def test_requires_sheet_choice_when_several(plan, tmp_path):
    rc = main(["detecter", str(plan), "-o", str(tmp_path / "o")])
    assert rc == 1  # plusieurs planches : il faut choisir
    rc = main(["calculer", str(plan), "--planche", "etage courant", "--niveaux", "3", "-o", str(tmp_path / "o")])
    assert rc == 0
    bld = Building.load(tmp_path / "o" / "modele.json")
    res = run(bld, LoadSettings(), get_code("bael"))
    assert all(r.design.ok for r in res.columns)


def test_forced_column_layer(plan):
    d = crop(import_plan(plan), select_sheet(find_sheets(import_plan(plan)), "2").bbox)
    bld = build_model(d, column_layer="COTATI0N")
    assert len(bld.columns) == 13
    bld = build_model(d, column_layer="INEXISTANT")
    assert len(bld.columns) == 0


@pytest.mark.skipif(find_dwg2dxf() is None or shutil.which("dxf2dwg") is None, reason="LibreDWG non installé")
def test_dwg_through_libredwg(plan, tmp_path):
    import subprocess

    dwg = tmp_path / "archi.dwg"
    subprocess.run(["dxf2dwg", "-y", "-o", str(dwg), str(plan)], check=True, capture_output=True)
    sheets = find_sheets(import_plan(dwg))
    assert len(sheets) == 2
