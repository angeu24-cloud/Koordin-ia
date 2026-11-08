"""Application web : comptes, projets, équipe et droits, plan, calcul, modèle, fichiers."""
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from baticalc.sample import write_sample_dxf
from baticalc.web import create_app


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
    assert ana.get(f"/api/projets/{pid}/fichiers/..%2Fbaticalc.json").status_code in (400, 404)

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
    assert r.status_code == 200 and "BatiCalc" in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/manifest.webmanifest").json()["short_name"] == "BatiCalc"


def test_old_database_is_taken_over(tmp_path):
    """Données créées sous l'ancien nom (koordinia.sqlite) : comptes repris automatiquement,
    même si une base vide a déjà été créée sous le nouveau nom."""
    from baticalc.web.storage import Storage

    st = Storage(tmp_path)
    st.create_user("ancien@bet.ci", "Ancien", "motdepasse1")
    st.db.close()
    (tmp_path / "baticalc.sqlite").rename(tmp_path / "koordinia.sqlite")
    Storage(tmp_path / "vide").db.close()
    (tmp_path / "vide" / "baticalc.sqlite").rename(tmp_path / "baticalc.sqlite")   # base vide nouvelle
    st2 = Storage(tmp_path)
    assert st2.authenticate("ancien@bet.ci", "motdepasse1")
    assert not (tmp_path / "koordinia.sqlite").exists()


def test_signup_rules(tmp_path):
    """Serveur sur internet : inscriptions fermées ou protégées par un code d'invitation."""
    def signup(app, email, **extra):
        return TestClient(app).post("/api/compte/inscription", json={"email": email, "nom": "X",
                                                                     "mot_de_passe": "motdepasse1", **extra})

    closed = create_app(tmp_path / "a", sync_jobs=True, inscription="fermee")
    assert TestClient(closed).get("/api/compte/inscription").json() == {"ouverte": True, "code": False, "premier": True}
    assert signup(closed, "admin@bet.ci").status_code == 200          # premier compte = administrateur
    assert signup(closed, "intrus@x.com").status_code == 403
    assert TestClient(closed).get("/api/compte/inscription").json()["ouverte"] is False

    coded = create_app(tmp_path / "b", sync_jobs=True, code_inscription="BET-2026")
    assert signup(coded, "admin@bet.ci").status_code == 200           # premier compte : sans code
    assert signup(coded, "collegue@bet.ci").status_code == 403
    assert signup(coded, "collegue@bet.ci", code="faux").status_code == 403
    assert signup(coded, "collegue@bet.ci", code="BET-2026").status_code == 200


def test_several_plan_files(app, tmp_path):
    """Plusieurs fichiers déposés ensemble : assemblés comme des planches ; ajout et retrait."""
    from baticalc.sample import write_sample_dxf

    ana = client(app, "multi@bet.ci", "Multi")
    pid = ana.post("/api/projets", json={"nom": "Multi"}).json()["id"]
    a = write_sample_dxf(tmp_path / "rdc.dxf")
    b = write_sample_dxf(tmp_path / "etage_1.dxf")
    with open(a, "rb") as fa, open(b, "rb") as fb:
        r = ana.post(f"/api/projets/{pid}/plan", files=[("fichiers", ("rdc.dxf", fa, "application/dxf")),
                                                        ("fichiers", ("etage_1.dxf", fb, "application/dxf"))])
    assert r.status_code == 200, r.text
    assert r.json()["fichiers"] == ["rdc.dxf", "etage_1.dxf"]
    p = ana.get(f"/api/projets/{pid}").json()
    assert p["configuration"]["projet"]["plan"] == ["plans/rdc.dxf", "plans/etage_1.dxf"]
    titres = [s["titre"] for s in p["analyse"]["planches"]]
    assert "PLAN RDC" in titres and "PLAN ETAGE 1" in titres
    r = ana.delete(f"/api/projets/{pid}/plan/etage_1.dxf")
    assert r.status_code == 200 and r.json()["fichiers"] == ["rdc.dxf"]
    with open(b, "rb") as fb:
        r = ana.post(f"/api/projets/{pid}/plan?mode=ajouter", files=[("fichiers", ("etage_1.dxf", fb, "application/dxf"))])
    assert r.json()["fichiers"] == ["rdc.dxf", "etage_1.dxf"]


def test_structure_editor(app, tmp_path):
    ana = client(app, "ana@bet.ci", "Ana")
    pid = ana.post("/api/projets", json={"nom": "Édition"}).json()["id"]
    assert ana.get(f"/api/projets/{pid}/structure").status_code == 404
    plan = write_sample_dxf(tmp_path / "plan.dxf")
    with open(plan, "rb") as f:
        ana.post(f"/api/projets/{pid}/plan", files={"fichier": ("plan.dxf", f, "application/dxf")})
    r = ana.post(f"/api/projets/{pid}/structure/proposer")
    assert r.status_code == 200, r.text
    assert ana.get(f"/api/taches/{r.json()['tache']}").json()["status"] == "termine"
    data = ana.get(f"/api/projets/{pid}/structure").json()
    assert data["source"] == "auto" and data["niveaux"]
    lv = data["niveaux"][0]
    n0, b0 = len(lv["poteaux"]), len(lv["poutres"])
    # ajout d'un poteau et d'une poutre, suppression d'un poteau et de ses poutres
    a = lv["poteaux"][0]
    lv["poteaux"].append({"id": "~P1", "x": a["x"] + 1.5, "y": a["y"], "b": 0.25, "h": 0.25})
    lv["poutres"].append({"id": "~B1", "a": a["id"], "b": "~P1", "l": 0.2, "h": 0.4})
    gone = lv["poteaux"].pop(-2)["id"]
    lv["poutres"] = [b for b in lv["poutres"] if gone not in (b["a"], b["b"])]
    r = ana.put(f"/api/projets/{pid}/structure", json=data)
    assert r.status_code == 200, r.text
    out = r.json()
    new = out["niveaux"][0]
    assert out["source"] == "edite" and len(new["poteaux"]) == n0
    assert not any(c["id"].startswith("~") for c in new["poteaux"])
    assert not any(b["id"].startswith("~") or b["a"].startswith("~") or b["b"].startswith("~") for b in new["poutres"])
    assert len({b["id"] for b in new["poutres"]}) == len(new["poutres"]) <= b0 + 1
    assert ana.get(f"/api/projets/{pid}").json()["configuration"]["projet"]["modele"] == "modele_edite.json"
    # section hors limites refusée
    bad = json.loads(json.dumps(out))
    bad["niveaux"][0]["poteaux"][0]["b"] = 3.0
    assert ana.put(f"/api/projets/{pid}/structure", json=bad).status_code == 400
    # calcul sur le modèle modifié
    assert ana.post(f"/api/projets/{pid}/calcul").status_code == 200
    assert ana.get(f"/api/projets/{pid}").json()["tache"]["status"] == "termine"
    # retour à la proposition automatique
    assert ana.delete(f"/api/projets/{pid}/structure").status_code == 200
    assert ana.get(f"/api/projets/{pid}/structure").json()["source"] == "auto"
    assert "modele" not in ana.get(f"/api/projets/{pid}").json()["configuration"]["projet"]
