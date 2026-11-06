"""Rapport géotechnique : extraction, unités, validation, application aux fondations."""
import json

import pymupdf
import pytest

from baticalc.cli import main
from baticalc.codes import get_code
from baticalc.design import run
from baticalc.geotech import GeotechData, Value, extract
from baticalc.importers import import_plan
from baticalc.model import LoadSettings
from baticalc.recognition import build_model
from baticalc.sample import write_sample_dxf

RAPPORT_SEMELLES = """RAPPORT D'ETUDE GEOTECHNIQUE - MISSION G2 AVP
Trois sondages penetrometriques ont ete realises jusqu'a 12 m de profondeur.
Aucune venue d'eau n'a ete observee ; la nappe n'a pas ete rencontree.
Nous recommandons des fondations superficielles de type semelles isolees,
ancrees a 1,80 m de profondeur minimum par rapport au terrain naturel.
La contrainte admissible du sol a l'ELS est de 2,5 bars a cette profondeur.
La contrainte de calcul a l'ELU est de 3,75 bars.
Les tassements absolus estimes sont inferieurs a 2 cm.
Les fondations profondes sont a exclure pour ce projet.
Le sol est de classe de sol C au sens de l'Eurocode 8.
"""

RAPPORT_PIEUX = """ETUDE DE SOL - Recommandations
Les sols superficiels sont compressibles (vases) jusqu'a 9 m.
La nappe phreatique a ete reperee a 1,20 m sous le terrain naturel.
Nous preconisons des fondations profondes sur pieux fores de diametre 600 mm ancres dans le sable compact a 14 m.
La charge admissible par pieu (ELS) est de 85 tonnes.
"""

RAPPORT_RADIER = """Synthese geotechnique
La capacite portante est faible : taux de travail admissible qadm = 120 kPa.
Il est recommande de fonder l'ouvrage sur un radier general ancre a 1,00 m.
"""


def _pdf(path, text):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=9)
    doc.save(path)
    return path


def test_extract_shallow(tmp_path):
    g = extract(_pdf(tmp_path / "r.pdf", RAPPORT_SEMELLES))
    assert g.sigma_sol == pytest.approx(0.25)
    assert g.contrainte_elu.value == pytest.approx(0.375)
    assert g.depth == pytest.approx(1.8)
    assert g.foundation == "superficielles"
    assert g.nappe.value == "absente"
    assert g.tassement.value == pytest.approx(2.0)
    assert g.classe_sismique.value == "C"
    assert "2,5 bars" in g.contrainte_admissible_els.source  # traçabilité
    assert not g.valide


def test_extract_piles_units(tmp_path):
    g = extract(_pdf(tmp_path / "p.pdf", RAPPORT_PIEUX))
    assert g.foundation == "pieux"
    assert g.water_depth == pytest.approx(1.2)
    assert g.charge_pieu.value == pytest.approx(85 * 9.81, rel=1e-3)
    assert g.diametre_pieu.value == pytest.approx(0.6)


def test_extract_raft_kpa(tmp_path):
    g = extract(_pdf(tmp_path / "x.pdf", RAPPORT_RADIER))
    assert g.sigma_sol == pytest.approx(0.12)
    assert g.foundation == "radier"
    assert g.depth == pytest.approx(1.0)


def test_scanned_report_rejected(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "scan.pdf")
    with pytest.raises(ValueError, match="scanné"):
        extract(tmp_path / "scan.pdf")


def test_json_roundtrip_and_manual_values(tmp_path):
    g = extract(_pdf(tmp_path / "r.pdf", RAPPORT_SEMELLES))
    g.save(tmp_path / "geotech.json")
    d = json.loads((tmp_path / "geotech.json").read_text(encoding="utf-8"))
    d["valide"] = True
    d["contrainte_admissible_els"] = 0.22          # correction saisie à la main par l'ingénieur
    (tmp_path / "geotech.json").write_text(json.dumps(d), encoding="utf-8")
    g2 = GeotechData.load(tmp_path / "geotech.json")
    assert g2.valide and g2.sigma_sol == pytest.approx(0.22)


@pytest.fixture
def bld(tmp_path):
    return build_model(import_plan(write_sample_dxf(tmp_path / "p.dxf")), n_levels=4)


def test_footings_use_report(bld, tmp_path):
    code = get_code("bael")
    g = extract(_pdf(tmp_path / "r.pdf", RAPPORT_SEMELLES))
    res = run(bld, LoadSettings(), code, geotech=g)
    assert res.sigma_sol == pytest.approx(0.25)
    assert any("NON VALIDÉES" in w for w in res.warnings)
    ref = run(bld, LoadSettings(), code, sigma_sol=0.25)  # même contrainte, sans ancrage
    f1 = {f.column_id: f.design for f in res.footings}
    f0 = {f.column_id: f.design for f in ref.footings}
    # les terres au-dessus de la semelle (ancrage 1,80 m) alourdissent la charge au sol
    assert all(f1[k].nser > f0[k].nser for k in f1)
    # une contrainte imposée reste prioritaire
    assert run(bld, LoadSettings(), code, sigma_sol=0.30, geotech=g).sigma_sol == 0.30


def test_piles_and_raft(bld, tmp_path):
    code = get_code("bael")
    gp = extract(_pdf(tmp_path / "p.pdf", RAPPORT_PIEUX))
    res = run(bld, LoadSettings(), code, geotech=gp)
    assert res.foundation_type == "pieux" and not res.footings
    assert all(p["n_pieux"] >= 1 for p in res.piles)
    assert any("Nappe à 1.2 m" in w for w in res.warnings)
    gr = extract(_pdf(tmp_path / "x.pdf", RAPPORT_RADIER))
    res = run(bld, LoadSettings(), code, geotech=gr)
    assert res.raft and res.raft["epaisseur"] >= res.raft["portee"] / 20
    assert res.raft["sigma"] == pytest.approx((res.raft["nser"] + 25 * res.raft["aire"] * res.raft["epaisseur"])
                                              / res.raft["aire"] / 1000)


def test_cli_geotech(tmp_path):
    rapport = _pdf(tmp_path / "r.pdf", RAPPORT_SEMELLES)
    assert main(["geotech", str(rapport), "-o", str(tmp_path)]) == 0
    assert (tmp_path / "geotech.json").exists()
    plan = write_sample_dxf(tmp_path / "p.dxf")
    out = tmp_path / "res"
    assert main(["calculer", str(plan), "--niveaux", "3", "--geotech", str(tmp_path / "geotech.json"),
                 "-o", str(out)]) == 0
    r = json.loads((out / "resultats.json").read_text(encoding="utf-8"))
    assert r["configuration"]["sol"] is None and r["fondations"] == "superficielles"
    html = (out / "note_de_calcul.html").read_text(encoding="utf-8")
    assert "Données géotechniques" in html and "NON VALIDÉES" in html


def test_blank_template(tmp_path):
    assert main(["geotech", "--vierge", "-o", str(tmp_path)]) == 0
    g = GeotechData.load(tmp_path / "geotech.json")
    assert g.sigma_sol == 0.20 and not g.valide
