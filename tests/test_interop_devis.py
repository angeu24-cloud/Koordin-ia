"""Export / import IFC et devis (bordereau de prix, métré, Excel)."""
import json
from pathlib import Path

import openpyxl
import pytest

from baticalc import env

from baticalc.cli import main
from baticalc.codes import get_code
from baticalc.costing.bpu import import_bpu
from baticalc.costing.devis import build_devis, write_excel
from baticalc.costing.metre import DevisSettings
from baticalc.design import run
from baticalc.importers import import_plan
from baticalc.model import LoadSettings
from baticalc.recognition import build_model
from baticalc.sample import write_sample_dxf
from baticalc.takedown import compute_takedown

ifcopenshell = pytest.importorskip("ifcopenshell")

REAL_BPU = Path(env("BPU_REEL", "bordereau_reel_absent.xls"))  # bordereau officiel CI 2012


@pytest.fixture
def result(tmp_path):
    bld = build_model(import_plan(write_sample_dxf(tmp_path / "p.dxf")), n_levels=3)
    return bld, run(bld, LoadSettings(), get_code("bael"))


def test_ifc_export_valid(result, tmp_path):
    import ifcopenshell.validate

    from baticalc.interop.ifc_export import export_ifc

    _, res = result
    f = ifcopenshell.open(str(export_ifc(res, tmp_path / "m.ifc")))
    assert len(f.by_type("IfcBuildingStorey")) == 3
    assert len(f.by_type("IfcColumn")) == 36 and len(f.by_type("IfcFooting")) == 12
    assert f.by_type("IfcBeam") and len(f.by_type("IfcSlab")) == 3
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    assert log.statements == []
    # résultats de dimensionnement attachés aux éléments
    import ifcopenshell.util.element as ue

    psets = ue.get_psets(f.by_type("IfcColumn")[0])
    assert psets["BatiCalc_Dimensionnement"]["Armatures"].startswith(("4HA", "6HA", "8HA"))


def test_ifc_roundtrip(result, tmp_path):
    from baticalc.interop.ifc_export import export_ifc
    from baticalc.interop.ifc_import import import_ifc

    bld, res = result
    proj = import_ifc(export_ifc(res, tmp_path / "m.ifc"))
    assert [len(s.plan.columns) for s in proj.storeys] == [12, 12, 12]
    assert [s.height for s in proj.storeys] == pytest.approx([3.0, 3.0, 3.0])
    ls = LoadSettings(continuity=False, degression=False)
    t1, t2 = compute_takedown(bld, ls), compute_takedown(proj, ls)
    g1 = sum(s.g for v in t1.columns.values() for s in v if s.storey == 1)
    g2 = sum(s.g for v in t2.columns.values() for s in v if s.storey == 1)
    assert g2 == pytest.approx(g1, rel=0.03)


def test_ifc_as_input(result, tmp_path):
    from baticalc.interop.ifc_export import export_ifc

    _, res = result
    ifc = export_ifc(res, tmp_path / "m.ifc")
    out = tmp_path / "o"
    assert main(["calculer", str(ifc), "-o", str(out)]) == 0
    assert (out / "modele.ifc").exists() and (out / "projet.json").exists()


def _xlsx_bpu(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["BORDEREAU DES PRIX"])
    ws.append([])
    ws.append(["N°", "DESIGNATION", "UNITE", "P.U HT"])
    rows = [
        ("", "Lot n° 1 - TERRASSEMENTS", "", None), ("", "Fouilles en excavation", "", None),
        ("", "2ème catégorie", "m3", 1500), ("", "Fouilles en puits", "", None), ("", "2ème catégorie", "m3", 4000),
        ("", "Remblais des fouilles", "m3", 1300), ("", "Evacuation des déblais excédentaires", "m3", 5000),
        ("", "Lot n° 2 - GROS-ŒUVRE", "", None), ("", "BETON", "", None), ("", "Béton de propreté", "", None),
        ("", "Béton dosé 150 kg/m3", "m3", 50000), ("", "Béton de semelle", "", None),
        ("", "Béton dosé 350 kg/m3", "m3", 75000), ("", "Béton en élévation dosé à 350 kg/m3", "", None),
        ("", "Poteaux et raidisseurs", "m3", 78000), ("", "Poutres, chaînages et linteaux", "m3", 77000),
        ("", "PLANCHER", "", None), ("", "Hourdis alphilaire 16 +  4", "m²", 21000),
        ("", "ARMATURES", "", None), ("", "Acier à haute adhérence (AHA)", "kg", 900),
    ]
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def test_bpu_xlsx_paths(tmp_path):
    b = import_bpu(_xlsx_bpu(tmp_path / "bpu.xlsx"))
    assert b.find(["FOUILLES EN PUITS", "2EME CATEGORIE"]).pu_ht == 4000
    assert b.find(["FOUILLES EN EXCAVATION", "2EME CATEGORIE"]).pu_ht == 1500
    assert b.find(["HOURDIS", r"16 \+ 4"]).pu_ht == 21000


def test_bpu_csv_ttc_only(tmp_path):
    p = tmp_path / "bpu.csv"
    p.write_text("Désignation;Unité;Prix unitaire TTC\nLot n° 2 - GROS OEUVRE;;\nAcier à haute adhérence;kg;1 180\n",
                 encoding="utf-8")
    b = import_bpu(p)
    assert b.items[0].pu_ht == pytest.approx(1000)


def test_devis_quantities_and_excel(result, tmp_path):
    _, res = result
    b = import_bpu(_xlsx_bpu(tmp_path / "bpu.xlsx"))
    dv = build_devis(res, b, DevisSettings(hourdis="16 + 4"))
    lines = {ln.code: ln for ln in dv.lines}
    # béton de semelles = Σ A·B·h
    assert lines["GO-SEM"].quantity == pytest.approx(sum(f.design.A * f.design.B * f.design.h for f in res.footings),
                                                     abs=0.01)
    assert lines["GO-SEM"].pu_ht == 75000
    # béton de poteaux = Σ b·h·H
    assert lines["GO-POT"].quantity == pytest.approx(sum(r.design.b * r.design.h * 3.0 for r in res.columns), abs=0.01)
    # remblai + volumes en place = fouille
    fou, rem = lines["TER-FOU"].quantity, lines["TER-REM"].quantity
    assert 0 < rem < fou
    assert lines["GO-HOU"].pu_ht == 21000 and lines["GO-HOU"].quantity > 0
    # coffrages absents du bordereau → prix à saisir, signalés
    assert lines["GO-CPO"].pu_ht is None and any("sans prix" in n for n in dv.notes)
    assert dv.total_ht == pytest.approx(sum(ln.amount for ln in dv.lines))
    path = write_excel(dv, tmp_path / "devis.xlsx")
    ws = openpyxl.load_workbook(path)["DQE"]
    formulas = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert any(f.startswith("=D") and "*E" in f for f in formulas)          # quantité × prix
    assert any(f.startswith("=SUM(") for f in formulas)                    # sous-totaux
    assert {"Métré", "Prix"} <= set(openpyxl.load_workbook(path).sheetnames)


def test_devis_without_bpu(result):
    _, res = result
    dv = build_devis(res, None, DevisSettings())
    assert dv.lines and all(ln.pu_ht is None for ln in dv.lines) and dv.total_ht == 0


@pytest.mark.skipif(not REAL_BPU.exists(), reason="bordereau réel non fourni (variable BATICALC_BPU_REEL)")
def test_real_bordereau_ci_2012():
    b = import_bpu(REAL_BPU)
    assert len(b.items) > 800
    assert b.find(["FOUILLES EN PUITS", "2EME CATEGORIE"]).pu_ht == pytest.approx(4027, abs=1)
    assert b.find(["BETON DE SEMELLE", "350"]).pu_ht == pytest.approx(77247, abs=1)
    assert b.find(["HAUTE ADHERENCE"]).pu_ht == pytest.approx(893, abs=1)


def test_cli_and_web_devis(tmp_path):
    from fastapi.testclient import TestClient

    from baticalc.web import create_app

    bpu = _xlsx_bpu(tmp_path / "bpu.xlsx")
    assert main(["bpu", str(bpu), "-o", str(tmp_path)]) == 0
    plan = write_sample_dxf(tmp_path / "plan.dxf")
    out = tmp_path / "o"
    assert main(["calculer", str(plan), "--niveaux", "2", "--bpu", str(tmp_path / "bpu.json"), "-o", str(out)]) == 0
    d = json.loads((out / "devis.json").read_text(encoding="utf-8"))
    assert d["total_ht"] > 0 and (out / "devis.xlsx").exists()

    app = create_app(tmp_path / "web", sync_jobs=True)
    c = TestClient(app)
    c.post("/api/compte/inscription", json={"email": "a@b.ci", "nom": "A", "mot_de_passe": "motdepasse1"})
    pid = c.post("/api/projets", json={"nom": "P"}).json()["id"]
    with open(plan, "rb") as f:
        c.post(f"/api/projets/{pid}/plan", files={"fichier": ("plan.dxf", f)})
    with open(bpu, "rb") as f:
        r = c.post(f"/api/projets/{pid}/bpu", files={"fichier": ("bpu.xlsx", f)})
    assert r.status_code == 200 and r.json()["articles"] >= 10
    c.put(f"/api/projets/{pid}/configuration", json={"devis": {"hourdis": "16 + 4"}, "lecture": {"niveaux": 2}})
    c.post(f"/api/projets/{pid}/calcul")
    d = c.get(f"/api/projets/{pid}/devis").json()
    assert d["devis"]["total_ht"] > 0 and d["bordereau"]["articles"] >= 10
    assert c.get(f"/api/projets/{pid}/fichiers/devis.xlsx").status_code == 200
    assert c.get(f"/api/projets/{pid}/fichiers/modele.ifc").status_code == 200
