from datetime import date

import pytest

from koordinpaie.calcul import (anciennete_annees, calculer_dict, charger_bareme, impot_bareme, its, nombre_parts,
                                prorata_mois, Salarie)

B = charger_bareme()


def test_bareme_its_par_tranches():
    tr = B["its"]["tranches"]
    assert impot_bareme(75000, tr) == 0
    assert impot_bareme(240000, tr) == pytest.approx(165000 * 0.16)
    assert impot_bareme(500000, tr) == pytest.approx(26400 + 260000 * 0.21)
    assert impot_bareme(10_000_000, tr) == pytest.approx(
        26400 + 560000 * .21 + 1600000 * .24 + 5600000 * .28 + 2000000 * .32)


def test_reduction_charges_de_famille():
    # 3 parts : 4 demi-parts au-delà de la première → 4 × 5 500
    assert its(349943, 3, B) == (49488, 22000, 27488)
    # la réduction ne rend jamais l'impôt négatif
    assert its(80000, 5, B)[2] == 0


def test_parts():
    assert nombre_parts(Salarie(date(2020, 1, 1)), B) == 1
    assert nombre_parts(Salarie(date(2020, 1, 1), marie=True, enfants=2), B) == 3
    assert nombre_parts(Salarie(date(2020, 1, 1), enfants=1), B) == 2      # parent isolé
    assert nombre_parts(Salarie(date(2020, 1, 1), marie=True, enfants=9), B) == 5
    assert nombre_parts(Salarie(date(2020, 1, 1), parts=2.5), B) == 2.5


def test_anciennete():
    assert anciennete_annees(date(2020, 3, 15), date(2026, 3, 14)) == 5
    assert anciennete_annees(date(2020, 3, 15), date(2026, 3, 15)) == 6
    r = calculer_dict({"date_embauche": "2024-11-30"}, {"salaire_base": 200000}, {}, 2026, 11)
    anc = next(g for g in r["gains"] if g["code"] == "ANC")
    assert anc["gain"] == 4000                        # 2 ans → 2 %
    r = calculer_dict({"date_embauche": "1990-01-01"}, {"salaire_base": 200000}, {}, 2026, 11)
    assert next(g for g in r["gains"] if g["code"] == "ANC")["gain"] == 50000   # plafond 25 %


def test_bulletin_complet_mensuel():
    r = calculer_dict({"date_embauche": "2020-03-01", "marie": True, "enfants": 2},
                      {"salaire_base": 300000, "transport": 30000,
                       "primes_fixes": [{"libelle": "Prime de rendement", "montant": 20000}]},
                      {"hs15": 6}, 2026, 11)
    assert r["brut"] == 300000 + 18000 + 11943 + 20000 + 30000
    assert r["brut_imposable"] == r["brut"] - 30000
    assert r["cnps_salarie"] == round(r["brut_imposable"] * 0.063)
    assert r["its"] == 27488
    assert r["net_a_payer"] == r["brut"] - r["cnps_salarie"] - 500 - r["its"]
    assert r["detail_patronal"]["CNPS_PF"] == 3750      # plafond 75 000
    assert r["cout_employeur"] == r["brut"] + r["charges_patronales"]


def test_plafond_retraite_et_transport_excedentaire():
    r = calculer_dict({"date_embauche": "2026-01-01"}, {"salaire_base": 5_000_000, "transport": 50000}, {}, 2026, 11)
    ret = next(c for c in r["cotisations"] if c["code"] == "CNPS_RET")
    assert ret["base"] == B["cnps"]["plafond_retraite"]
    assert r["brut_imposable"] == 5_000_000 + 20000     # 30 000 exonérés sur 50 000


def test_journalier_et_prorata():
    r = calculer_dict({"date_embauche": "2026-11-01"}, {"mode": "journalier", "salaire_base": 5000, "type": "JOURNALIER"},
                      {"jours": 20}, 2026, 11)
    assert r["gains"][0]["gain"] == 100000
    assert prorata_mois(2026, 11, date(2026, 11, 16), None) == 0.5
    assert prorata_mois(2026, 11, None, date(2026, 11, 3)) == 0.1
    r = calculer_dict({"date_embauche": "2026-11-16"}, {"salaire_base": 200000}, {"prorata": 0.5}, 2026, 11)
    assert r["brut"] == 100000


def test_absences_acompte_et_alerte_smig():
    r = calculer_dict({"date_embauche": "2026-01-01"}, {"salaire_base": 173330}, {"heures_absence": 10, "acompte": 20000},
                      2026, 11)
    assert next(g for g in r["gains"] if g["code"] == "ABS")["gain"] == -10000
    assert r["total_retenues"] == 20000
    r = calculer_dict({"date_embauche": "2026-01-01"}, {"salaire_base": 60000}, {}, 2026, 11)
    assert any("SMIG" in a for a in r["alertes"])


def test_bareme_personnalise():
    b = charger_bareme({"cnps": {"accident_travail": 0.05}})
    assert b["cnps"]["accident_travail"] == 0.05 and b["cnps"]["retraite_salarie"] == 0.063
    r = calculer_dict({"date_embauche": "2026-01-01"}, {"salaire_base": 200000}, {}, 2026, 11, b)
    assert r["detail_patronal"]["CNPS_AT"] == 3750
