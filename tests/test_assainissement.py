"""Assainissement autonome : fosse toutes eaux, puits d'infiltration, bac à graisses."""
import math

import pytest

from baticalc.mep.assainissement import SOLS, bac_graisses, fosse_toutes_eaux, infiltration


def test_fosse_volume_and_geometry():
    f = fosse_toutes_eaux(8, pieces=4, sejour_j=3)
    assert f.v_requis == pytest.approx(8 * 0.15 * 3 + 8 * 0.04 * 2)
    assert f.v_adopte == 4.5 and f.v_utile >= 4.5
    assert 2.0 <= f.longueur / f.largeur <= 3.0
    assert 0.6 <= f.longueur_1 / f.longueur <= 0.72
    assert f.ext_longueur == pytest.approx(f.longueur + f.cloison + 2 * f.voile)
    assert f.armatures["voiles"].startswith("HA10 e=15")
    small = fosse_toutes_eaux(4, pieces=4)
    assert small.v_adopte == 3.0          # minimum réglementaire (≤ 5 pièces principales)
    assert fosse_toutes_eaux(4, pieces=7).v_reglementaire == 5.0


def test_infiltration_by_soil():
    sand = infiltration(0.9, "sable")
    assert sand.surface_requise_m2 == pytest.approx(0.9 * 1.25 * 1000 / 50, rel=1e-3)
    r = sand.recommandee
    assert r.nombre == 1 and r.surface_m2 >= sand.surface_requise_m2
    assert math.pi * r.diametre * r.hauteur_active * r.nombre == pytest.approx(r.surface_m2, abs=0.1)
    silty = infiltration(0.9, "sable_limoneux")
    assert silty.recommandee.nombre >= 2
    clay = infiltration(0.9, "argile")
    assert clay.recommandee is None and "épandage" in clay.filiere
    assert set(SOLS) >= {"sable", "argile"}


def test_grease_trap():
    assert bac_graisses(distance_fosse_m=38)["necessaire"] is True
    assert bac_graisses(distance_fosse_m=6)["necessaire"] is False


def test_evacuation_network():
    from baticalc.mep.evacuation import Troncon, capacite, dimensionner, profil, q_ww, regard

    assert q_ww(["lavabo"]) == 0.5
    assert q_ww(["wc", "lavabo", "douche", "evier"]) == 2.0           # débit du WC gouverne
    assert q_ww(["wc"] * 10) == pytest.approx(0.5 * math.sqrt(20), abs=1e-3)
    assert capacite(110, 0.02) > capacite(110, 0.01)
    t = dimensionner(Troncon("T1", "R1", "R2", 8.0, 0.02, ["evier", "wc"]))
    assert t.dn == 110 and 0 < t.h_d <= 0.5 and t.v > 0
    ts = [Troncon("a", "R1", "R2", 10, 0.02), Troncon("b", "R2", "R3", 5, 0.01)]
    fe = profil(ts, -0.40)
    assert fe["R2"] == pytest.approx(-0.60) and fe["R3"] == pytest.approx(-0.65)
    assert regard(0.5) == "40 × 40" and regard(1.5) == "80 × 80"
