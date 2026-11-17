import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from koordinpaie.app import creer_app


@pytest.fixture()
def client(tmp_path):
    app = creer_app(tmp_path)
    with TestClient(app) as c:
        r = c.post("/api/inscription", json={"email": "admin@exemple.ci", "nom": "Admin", "mdp": "motdepasse1"})
        assert r.status_code == 200
        yield c


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_premier_compte_puis_inscription_fermee(client):
    assert ok(client.get("/api/etat"))["utilisateur"]["role"] == "admin"
    r = client.post("/api/inscription", json={"email": "x@exemple.ci", "nom": "X", "mdp": "motdepasse1"})
    assert r.status_code == 403


def test_parcours_complet(client):
    ok(client.put("/api/entreprise", json={"raison_sociale": "BTP Lagune SARL", "ville": "Abidjan", "taux_at": 5,
                                           "numero_cnps": "123456"}))
    sid = ok(client.post("/api/salaries", json={"nom": "KOUASSI", "prenoms": "Yao Serge", "marie": True, "enfants": 2,
                                                 "numero_cnps": "9988", "date_embauche": "2020-03-01"}))["id"]
    s = ok(client.get(f"/api/salaries/{sid}"))
    assert s["matricule"] == "S0001"

    cid = ok(client.post(f"/api/salaries/{sid}/contrats", json={
        "type": "CDI", "poste": "Chef de chantier", "categorie": "M1", "date_debut": "2020-03-01", "essai_mois": 3,
        "salaire_base": 300000, "transport": 30000,
        "primes_fixes": [{"libelle": "Prime de salissure", "montant": 10000, "imposable": True}]}))["id"]
    # avenant : augmentation au 1er novembre 2026
    ok(client.post(f"/api/contrats/{cid}/avenants", json={"date_effet": "2026-11-01", "objet": "Augmentation",
                                                           "modifications": {"salaire_base": 350000}}))

    # CDD qui se termine en novembre → indemnité de fin de contrat
    sid2 = ok(client.post("/api/salaries", json={"nom": "TRAORE", "prenoms": "Awa"}))["id"]
    ok(client.post(f"/api/salaries/{sid2}/contrats", json={
        "type": "CDD", "poste": "Maçon", "date_debut": "2026-11-01", "date_fin": "2026-11-15",
        "motif_cdd": "Surcroît d'activité", "salaire_base": 200000}))
    # contrat CDD sans date de fin refusé
    r = client.post(f"/api/salaries/{sid2}/contrats", json={"type": "CDD", "date_debut": "2026-11-01", "salaire_base": 1})
    assert r.status_code == 400

    pid = ok(client.post("/api/periodes", json={"annee": 2026, "mois": 11}))["id"]
    per = ok(client.get(f"/api/periodes/{pid}"))
    assert len(per["bulletins"]) == 2
    b1 = next(b for b in per["bulletins"] if b["salarie_id"] == sid)
    b2 = next(b for b in per["bulletins"] if b["salarie_id"] == sid2)
    assert b1["resultat"]["gains"][0]["gain"] == 350000                 # avenant appliqué
    assert b1["resultat"]["detail_patronal"]["CNPS_AT"] == 3750         # taux AT de l'entreprise (5 %)
    g2 = {g["code"]: g["gain"] for g in b2["resultat"]["gains"]}
    assert g2["BASE"] == 100000                                         # prorata 15/30
    assert g2["FINCDD"] == 3000                                         # 3 % du brut

    # éléments variables
    b = ok(client.put(f"/api/bulletins/{b1['id']}", json={"variables": {"hs15": 4, "acompte": 50000,
                                                                       "primes": [{"libelle": "Prime exceptionnelle", "montant": 25000}]}}))
    assert b["resultat"]["total_retenues"] == 50000
    assert any(g["libelle"] == "Prime exceptionnelle" for g in b["resultat"]["gains"])
    net = b["resultat"]["net_a_payer"]

    # documents
    r = client.get(f"/api/bulletins/{b1['id']}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = client.get(f"/api/contrats/{cid}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    import pymupdf
    texte = pymupdf.open("pdf", r.content)[0].get_text()
    assert "DURÉE INDÉTERMINÉE" in texte and "KOUASSI" in texte and "BTP Lagune" in texte
    r = client.get(f"/api/periodes/{pid}/bulletins.pdf")
    assert pymupdf.open("pdf", r.content).page_count >= 2
    r = client.get(f"/api/periodes/{pid}/livre.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Livre de paie", "Déclarations"]

    # clôture : bulletin figé même si le contrat change ensuite
    ok(client.post(f"/api/periodes/{pid}/cloture"))
    ok(client.post(f"/api/contrats/{cid}/avenants", json={"date_effet": "2026-11-01", "objet": "Correction",
                                                           "modifications": {"salaire_base": 999999}}))
    b = ok(client.get(f"/api/bulletins/{b1['id']}"))
    assert b["resultat"]["net_a_payer"] == net
    assert client.put(f"/api/bulletins/{b1['id']}", json={"variables": {}}).status_code == 400
    assert client.delete(f"/api/salaries/{sid}").status_code == 400     # bulletins clôturés

    # cumuls : décembre ajoute au cumul de novembre
    pid12 = ok(client.post("/api/periodes", json={"annee": 2026, "mois": 12}))["id"]
    per12 = ok(client.get(f"/api/periodes/{pid12}"))
    assert len(per12["bulletins"]) == 1                                  # le CDD est terminé
    b12 = ok(client.get(f"/api/bulletins/{per12['bulletins'][0]['id']}"))
    assert b12["cumuls"]["brut"] == b["resultat"]["brut"] + b12["resultat"]["brut"]

    # réouverture refusée tant qu'une période plus récente est clôturée
    ok(client.post(f"/api/periodes/{pid12}/cloture"))
    assert client.post(f"/api/periodes/{pid}/reouverture").status_code == 400
    ok(client.post(f"/api/periodes/{pid12}/reouverture"))
    ok(client.post(f"/api/periodes/{pid}/reouverture"))


def test_alertes_et_fin_de_contrat(client):
    sid = ok(client.post("/api/salaries", json={"nom": "BAMBA"}))["id"]
    fin = (date.today() + timedelta(days=10)).isoformat()
    cid = ok(client.post(f"/api/salaries/{sid}/contrats", json={
        "type": "CDD", "poste": "Ferrailleur", "date_debut": date.today().isoformat(), "date_fin": fin,
        "salaire_base": 50000}))["id"]
    textes = [a["texte"] for a in ok(client.get("/api/alertes"))]
    assert any("se termine" in t for t in textes)
    assert any("SMIG" in t for t in textes)
    assert any("CNPS" in t for t in textes)
    ok(client.post(f"/api/contrats/{cid}/fin", json={"date_fin": fin, "motif": "Arrivée du terme"}))
    textes = [a["texte"] for a in ok(client.get("/api/alertes"))]
    assert not any("se termine" in t for t in textes)


def test_droits_lecteur(client):
    ok(client.post("/api/utilisateurs", json={"email": "lecteur@exemple.ci", "nom": "L", "mdp": "motdepasse2",
                                              "role": "lecteur"}))
    client.post("/api/deconnexion")
    ok(client.post("/api/connexion", json={"email": "lecteur@exemple.ci", "mdp": "motdepasse2"}))
    assert client.get("/api/salaries").status_code == 200
    assert client.post("/api/salaries", json={"nom": "X"}).status_code == 403
    assert client.put("/api/bareme", json={}).status_code == 403
    assert client.get("/api/utilisateurs").status_code == 403
    client.post("/api/deconnexion")
    assert client.get("/api/salaries").status_code == 401


def test_bareme_modifiable(client):
    bar = ok(client.get("/api/bareme"))["bareme"]
    bar["smig_mensuel"] = 80000
    ok(client.put("/api/bareme", json=bar))
    assert ok(client.get("/api/bareme"))["bareme"]["smig_mensuel"] == 80000
    assert client.put("/api/bareme", json={"inconnu": 1}).status_code == 400
    ok(client.delete("/api/bareme"))
    assert ok(client.get("/api/bareme"))["bareme"]["smig_mensuel"] == 75000


def test_interface_servie(client):
    assert "Koordin Paie" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
