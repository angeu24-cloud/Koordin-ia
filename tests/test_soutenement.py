"""Murs de soutènement : poussée de Rankine, stabilité externe, ferraillage, métré, commande et outil web."""
import json
import math

import pytest

from baticalc.codes import get_code
from baticalc.soutenement import RetainingWall, Soil, design_wall, ka_rankine, stability, wall_dxf, wall_html


def test_ka_rankine():
    assert ka_rankine(30) == pytest.approx(1 / 3, rel=1e-6)
    assert ka_rankine(35) == pytest.approx(math.tan(math.radians(27.5)) ** 2, rel=1e-6)
    assert ka_rankine(30, 20) > ka_rankine(30)          # talus incliné : poussée plus forte


def test_reference_wall_3m():
    """H = 3 m, q = 10 kN/m², φ = 30°, sol 0,15 MPa : semelle ≈ 0,7 H, voile HA12 e = 12,5 cm."""
    r = design_wall(RetainingWall(height=3.0, surcharge=10, sigma_sol=0.15, length=25), get_code("bael", cover=0.05))
    assert r.ok
    g, st, ra = r.geometry, r.stability, r.reinforcement
    assert 2.0 <= g["B"] <= 2.6 and g["t_base"] >= 0.25
    assert st["renversement"]["Fs"] >= 1.5 and st["glissement"]["Fs"] >= 1.5
    assert abs(st["excentricite"]["e"]) <= g["B"] / 6
    # moment en pied du voile : 1,35·Ka·γ·H³/6 + 1,5·Ka·q·H²/2
    assert ra["voile"]["Mu_kNm"] == pytest.approx(1.35 * 18 * 27 / 18 + 1.5 * 10 * 9 / 6, rel=0.01)
    assert ra["voile"]["As_reel"] >= ra["voile"]["As_cm2_m"]
    q = r.quantities
    assert q["total"]["beton_m3"] == pytest.approx(25 * q["par_ml"]["beton_m3"], rel=1e-3)
    assert 40 <= q["ratio_acier_kg_m3"] <= 120


def test_water_and_slope_widen_the_base():
    c = get_code("bael", cover=0.05)
    dry = design_wall(RetainingWall(height=3.0), c)
    wet = design_wall(RetainingWall(height=3.0, water=1.0), c)
    slope = design_wall(RetainingWall(height=3.0, slope=20), c)
    assert wet.geometry["B"] > dry.geometry["B"] and slope.geometry["B"] > dry.geometry["B"]
    assert wet.forces["poussee_eau_kN_ml"] > 0 and wet.ok and slope.ok


def test_imposed_small_base_fails_and_steep_slope_refused():
    c = get_code("bael", cover=0.05)
    w = RetainingWall(height=3.0, toe=0.2, heel=0.4, h_base=0.3)
    r = design_wall(w, c)
    assert not r.ok and any("géométrie imposée" in n for n in r.notes)
    st = stability(w, r.geometry)
    assert st["renversement"]["Fs"] < 1.5 or st["glissement"]["Fs"] < 1.5
    with pytest.raises(ValueError):
        design_wall(RetainingWall(height=3.0, slope=35, soil=Soil(phi=30)), c)


def test_ec2_and_outputs(tmp_path):
    c = get_code("ec2", cover=0.05)
    r = design_wall(RetainingWall(height=4.0, surcharge=15, sigma_sol=0.20, length=10), c)
    assert r.ok
    wall_dxf(r, tmp_path / "coupe.dxf")
    html = wall_html(r, c)
    assert (tmp_path / "coupe.dxf").stat().st_size > 1000 and "Eurocode 2" in html and "vérifié" in html


def test_cli(tmp_path):
    from baticalc.cli import main

    rc = main(["soutenement", "--hauteur", "2.5", "--longueur", "12", "--sol", "0.12", "-o", str(tmp_path)])
    assert rc == 0
    d = json.loads((tmp_path / "soutenement.json").read_text(encoding="utf-8"))
    assert d["ok"] and d["quantities"]["longueur"] == 12
    assert (tmp_path / "note_soutenement.html").exists() and (tmp_path / "coupe_mur_soutenement.dxf").exists()


def test_web_tool(tmp_path):
    from fastapi.testclient import TestClient

    from baticalc.web import create_app

    c = TestClient(create_app(tmp_path / "d", sync_jobs=True))
    c.post("/api/compte/inscription", json={"email": "a@b.ci", "nom": "A", "mot_de_passe": "motdepasse1"})
    r = c.post("/api/outils/soutenement", json={"hauteur": "3", "longueur": "20", "surcharge": "10", "nappe": ""})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["resultat"]["ok"] and j["dxf_base64"] and "NOTE DE CALCUL" in j["note_html"]
    assert c.post("/api/outils/soutenement", json={"hauteur": "40"}).status_code == 400
