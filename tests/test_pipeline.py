import json

import pymupdf
import pytest

from baticalc.cli import main
from baticalc.codes import get_code
from baticalc.design import run
from baticalc.geometry import rect_from_points
from baticalc.importers import import_plan
from baticalc.importers.pdf_importer import PdfImportError, detect_scale
from baticalc.model import Building, LoadSettings
from baticalc.recognition import build_model
from baticalc.sample import write_sample_dxf, write_sample_pdf
from baticalc.takedown import compute_takedown, degression_coef


def test_rect_from_points():
    assert rect_from_points([(0, 0), (1, 0), (1, 2), (0, 2)]) == (0, 0, 1, 2)
    assert rect_from_points([(0, 0), (1, 0), (1, 2), (0, 2), (0, 0)]) == (0, 0, 1, 2)
    assert rect_from_points([(0, 0), (1, 0), (1.5, 2), (0, 2)]) is None


def test_degression():
    assert [degression_coef(m) for m in (1, 2, 3, 4)] == [1.0, 0.95, 0.90, 0.85]
    assert degression_coef(5) == pytest.approx(0.8)
    assert degression_coef(10) == pytest.approx(0.65)


@pytest.mark.parametrize("units_mm,with_layer", [(True, True), (False, True), (True, False)])
def test_dxf_recognition(tmp_path, units_mm, with_layer):
    f = write_sample_dxf(tmp_path / "plan.dxf", units_mm=units_mm, with_layer=with_layer)
    bld = build_model(import_plan(f), n_levels=3)
    assert len(bld.columns) == 12
    assert len(bld.beams) == 17
    assert len(bld.panels) == 6
    assert bld.grid_x == pytest.approx([0, 4.0, 8.5, 12.5])
    assert bld.grid_y == pytest.approx([0, 5.0, 9.0])
    assert all(c.b == pytest.approx(0.30) for c in bld.columns)


def test_pdf_recognition_and_scale_detection(tmp_path):
    f = write_sample_pdf(tmp_path / "plan.pdf", scale=50)
    bld = build_model(import_plan(f), n_levels=2)
    assert len(bld.columns) == 12 and len(bld.panels) == 6
    assert bld.grid_x == pytest.approx([0, 4.0, 8.5, 12.5], abs=0.01)
    assert any("1/50" in w for w in bld.warnings)


def test_scale_regex():
    assert detect_scale("PLAN RDC  Ech : 1/100") == 100
    assert detect_scale("Echelle 1:50") == 50
    assert detect_scale("rien ici") is None


def test_scanned_pdf_is_rejected(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), pixmap=pix)
    f = tmp_path / "scan.pdf"
    doc.save(f)
    with pytest.raises(PdfImportError, match="scanné"):
        import_plan(f, scale=100)


@pytest.mark.parametrize("footprint,area", [(False, 12.5 * 9.0), (True, 13.0 * 9.5)])
def test_takedown_equilibrium(tmp_path, footprint, area):
    """Sans majoration de continuité ni dégression, Σ réactions = Σ charges appliquées."""
    f = write_sample_dxf(tmp_path / "plan.dxf")
    bld = build_model(import_plan(f), n_levels=3, floor_height=3.0, footprint=footprint)
    ls = LoadSettings(continuity=False, degression=False)
    td = compute_takedown(bld, ls)
    # contour = axes (mailles) ou nu extérieur des murs de façade (épaisseur 25 cm au-delà des axes)
    assert td.slab_area == pytest.approx(area, rel=0.02)
    area = td.slab_area
    cols = bld.column_map()
    beams_g = sum(25 * b.b * b.h * b.length(cols) for b in bld.beams)
    cols_g = sum(25 * c.b * c.h * 3.0 for c in bld.columns)
    g_expected = area * (2 * td.surface_g_floor + td.surface_g_roof) + 3 * beams_g + 3 * cols_g
    q_expected = area * (2 * td.surface_q_floor + td.surface_q_roof)
    base = [s for st in td.columns.values() for s in st if s.storey == 1]
    assert sum(s.g for s in base) == pytest.approx(g_expected, rel=1e-9)
    assert sum(s.q for s in base) == pytest.approx(q_expected, rel=1e-9)


def test_dalle_pleine_distribution_balances(tmp_path):
    f = write_sample_dxf(tmp_path / "plan.dxf")
    bld = build_model(import_plan(f), n_levels=1, footprint=False)
    td = compute_takedown(bld, LoadSettings(floor_type="dalle_pleine", continuity=False))
    q_tot = sum(bl.q_tot for bl in td.roof_loads.values())
    assert q_tot == pytest.approx(12.5 * 9.0 * td.surface_q_roof)


def test_raster_matches_classic_load_distribution(tmp_path):
    """Panneau 4,5 × 4 en corps creux : chaque poutre de 4,5 m reçoit p·2,0 m ; en dalle pleine,
    trapèze lx/4·(2ly − lx) et M0 conforme à la formule p·lx/2·(1 − ρ²/3)·L²/8."""
    f = write_sample_dxf(tmp_path / "plan.dxf")
    bld = build_model(import_plan(f), n_levels=1, footprint=False)
    cols = bld.column_map()
    # poutre X centrale entre les files B (y = 5) et C (y = 9), travée 4,5 m (x 4 → 8,5), bord haut du plancher
    top = next(b for b in bld.beams if b.direction == "X" and cols[b.start].x == pytest.approx(4.0)
               and cols[b.start].y == pytest.approx(9.0))
    ls = LoadSettings(continuity=False, q_roof=1.0)
    td = compute_takedown(bld, ls)
    assert td.roof_loads[top.id].trib_area == pytest.approx(4.5 * 2.0, rel=0.01)
    td2 = compute_takedown(bld, LoadSettings(floor_type="dalle_pleine", continuity=False, q_roof=1.0))
    lx, ly = 4.0, 4.5
    rho = lx / ly
    assert td2.roof_loads[top.id].trib_area == pytest.approx(lx / 4 * (2 * ly - lx), rel=0.02)
    m0_theory = lx / 2 * (1 - rho ** 2 / 3) * ly ** 2 / 8
    assert td2.roof_loads[top.id].q_m0 == pytest.approx(m0_theory, rel=0.03)


@pytest.mark.parametrize("norme", ["bael", "ec2"])
def test_full_design(tmp_path, norme):
    f = write_sample_dxf(tmp_path / "plan.dxf")
    bld = build_model(import_plan(f), n_levels=5)
    res = run(bld, LoadSettings(), get_code(norme))
    assert len(res.columns) == 12 * 5
    assert len(res.footings) == 12
    assert all(r.design.ok for r in res.columns)
    assert all(f.design.ok for f in res.footings)
    # le poteau central du RDC est plus chargé que le poteau d'angle
    nu = {(r.column_id, r.storey): r.nu for r in res.columns}
    assert nu[("P6", 1)] > nu[("P1", 1)] > nu[("P1", 5)]


def test_model_json_roundtrip(tmp_path):
    f = write_sample_dxf(tmp_path / "plan.dxf")
    bld = build_model(import_plan(f), n_levels=2)
    bld.save(tmp_path / "m.json")
    again = Building.load(tmp_path / "m.json")
    assert again.to_dict() == bld.to_dict()


def test_cli_end_to_end(tmp_path):
    assert main(["exemple", "-o", str(tmp_path / "ex")]) == 0
    out = tmp_path / "res"
    rc = main(["calculer", str(tmp_path / "ex" / "exemple_plan.pdf"), "--niveaux", "4", "--norme", "bael",
               "-o", str(out)])
    assert rc == 0
    for name in ("note_de_calcul.pdf", "note_de_calcul.html", "plan_coffrage_etage_courant.dxf",
                 "plan_coffrage_terrasse.dxf", "plan_fondations.dxf", "plans_ferraillage.dxf",
                 "controle_modele.dxf", "modele.json", "resultats.json"):
        assert (out / name).exists(), name
    data = json.loads((out / "resultats.json").read_text(encoding="utf-8"))
    assert data["metre"]["poteaux"]["acier_kg"] > 0
    # recalcul en EC2 à partir du modèle JSON
    assert main(["calculer", "--modele", str(out / "modele.json"), "--norme", "ec2", "-o", str(out / "ec2")]) == 0


def test_cli_from_dxf_writes_json(tmp_path):
    f = write_sample_dxf(tmp_path / "plan.dxf")
    assert main(["calculer", str(f), "--niveaux", "2", "--norme", "ec2", "-o", str(tmp_path / "o")]) == 0
    data = json.loads((tmp_path / "o" / "resultats.json").read_text(encoding="utf-8"))
    assert all(isinstance(p["ok"], bool) for p in data["poteaux"])


def test_cli_rejects_cm66(tmp_path):
    f = write_sample_dxf(tmp_path / "plan.dxf")
    assert main(["calculer", str(f), "--norme", "cm66", "-o", str(tmp_path / "o")]) == 1
