"""Application web : comptes, projets, équipe et droits, plan, calcul, modèle, fichiers."""
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from koordinia.sample import write_sample_dxf
from koordinia.web import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "donnees", sync_jobs=True)


def client(app, email, name="Test"):
    c = TestClient(app)
    r = c.post("/api/compte/inscription", json={"email": email, "nom": name, "mot_de_passe": "motdepasse1"})
    assert r.status_code == 200, r.text
    return c


def test_accounts(app):
    c = client(app, "ana@bet.ci", "Ana")
    assert c.get("/api/compte").json()["nom"] == "Ana"
    assert TestClient(app).post("/api/compte/inscription", json={"email": "ana@bet.ci", "nom": "x",
                                                                 "mot_de_passe": "motdepasse1"}).status_code == 409
    assert TestClient(app).post("/api/compte/connexion", json={"email": "ana@bet.ci",
                                                               "mot_de_passe": "faux"}).status_code == 401
    c2 = TestClient(app)
    assert c2.post("/api/compte/connexion", json={"email": "ANA@bet.ci", "mot_de_passe": "motdepasse1"}).status_code == 200
    c2.post("/api/compte/deconnexion")
    assert c2.get("/api/compte").status_code == 401
    assert TestClient(app).post("/api/compte/inscription", json={"email": "x@y.z", "nom": "x",
                                                                 "mot_de_passe": "court"}).status_code == 400


def test_full_workflow_and_team(app, tmp_path):
    ana = client(app, "ana@bet.ci", "Ana")
    ben = client(app, "ben@bet.ci", "Ben")
    pid = ana.post("/api/projets", json={"nom": "Immeuble test"}).json()["id"]
    # Ben ne voit pas encore le projet
    assert ben.get(f"/api/projets/{pid}").status_code == 404
    assert ben.get("/api/projets").json() == []
    # import du plan → analyse (synchrone en test)
    plan = write_sample_dxf(tmp_path / "plan.dxf")
    with open(plan, "rb") as f:
        r = ana.post(f"/api/projets/{pid}/plan", files={"fichier": ("plan.dxf", f, "application/dxf")})
    assert r.status_code == 200, r.text
    p = ana.get(f"/api/projets/{pid}").json()
    assert p["analyse"]["fichier"] == "plan.dxf"
    assert p["tache"]["status"] == "termine"
    # hypothèses
    r = ana.put(f"/api/projets/{pid}/configuration", json={"lecture": {"niveaux": 3, "hauteur": 3.0},
                                                          "charges": {"q": 2.5}, "reglement": {"norme": "ec2", "fe": 500}})
    assert r.json()["charges"]["q"] == 2.5
    # rapport géotechnique
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 560, 800),
                                  "Nous recommandons des semelles isolees ancrees a 1,50 m. "
                                  "La contrainte admissible du sol a l'ELS est de 2 bars.", fontsize=9)
    doc.save(tmp_path / "geo.pdf")
    with open(tmp_path / "geo.pdf", "rb") as f:
        g = ana.post(f"/api/projets/{pid}/geotech", files={"fichier": ("geo.pdf", f, "application/pdf")}).json()
    assert g["contrainte_admissible_els"]["value"] == pytest.approx(0.2)
    g["valide"] = True
    assert ana.put(f"/api/projets/{pid}/geotech", json=g).json()["valide"] is True
    # calcul
    r = ana.post(f"/api/projets/{pid}/calcul")
    job = ana.get(f"/api/taches/{r.json()['tache']}").json()
    assert job["status"] == "termine", job["error"]
    p = ana.get(f"/api/projets/{pid}").json()
    assert p["resultats"]["norme"].startswith("Eurocode 2")
    assert len(p["resultats"]["niveaux"]) == 3
    assert "note_de_calcul.pdf" in p["fichiers"]
    m = ana.get(f"/api/projets/{pid}/modele").json()
    assert len(m["niveaux"]) == 3 and m["niveaux"][0]["colonnes"] and m["niveaux"][0]["dalle"]
    assert m["semelles"]
    pdf = ana.get(f"/api/projets/{pid}/fichiers/note_de_calcul.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert ana.get(f"/api/projets/{pid}/fichiers/..%2Fkoordinia.json").status_code in (400, 404)

    # équipe : Ben lecteur → consulte mais ne modifie pas
    assert ana.post(f"/api/projets/{pid}/membres", json={"email": "ben@bet.ci", "role": "lecteur"}).status_code == 200
    assert ben.get(f"/api/projets/{pid}").json()["role"] == "lecteur"
    assert ben.get(f"/api/projets/{pid}/modele").status_code == 200
    assert ben.post(f"/api/projets/{pid}/calcul").status_code == 403
    assert ben.put(f"/api/projets/{pid}/configuration", json={"charges": {"q": 9}}).status_code == 403
    assert ben.delete(f"/api/projets/{pid}").status_code == 403
    # Ben éditeur → peut calculer, pas gérer l'équipe
    ana.post(f"/api/projets/{pid}/membres", json={"email": "ben@bet.ci", "role": "editeur"})
    assert ben.post(f"/api/projets/{pid}/calcul").status_code == 200
    assert ben.post(f"/api/projets/{pid}/membres", json={"email": "ana@bet.ci", "role": "lecteur"}).status_code == 403
    # invitation d'un compte inexistant
    assert ana.post(f"/api/projets/{pid}/membres", json={"email": "zoe@bet.ci", "role": "editeur"}).status_code == 404
    # journal d'activité partagé
    texts = [a["text"] for a in ben.get(f"/api/projets/{pid}").json()["journal"]]
    assert any("Calcul terminé" in t for t in texts) and any("Ben ajouté" in t for t in texts)
    # suppression par le propriétaire
    assert ana.delete(f"/api/projets/{pid}").status_code == 200
    assert ben.get(f"/api/projets/{pid}").status_code == 404


def test_bad_upload(app, tmp_path):
    ana = client(app, "ana@bet.ci")
    pid = ana.post("/api/projets", json={"nom": "P"}).json()["id"]
    r = ana.post(f"/api/projets/{pid}/plan", files={"fichier": ("virus.exe", b"MZ....", "application/octet-stream")})
    assert r.status_code == 400
    assert ana.post(f"/api/projets/{pid}/calcul").status_code == 400  # pas de plan


def test_interface_served(app):
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "Koordin-IA" in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/manifest.webmanifest").json()["short_name"] == "Koordin-IA"
