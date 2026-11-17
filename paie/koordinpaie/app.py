"""Application web (API JSON + interface) : salariés, contrats, paie."""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import documents, paie
from .calcul import BAREME_DEFAUT, calculer_dict, charger_bareme
from .stockage import ROLES, Stockage

COOKIE = "koordinpaie_session"
STATIC = Path(__file__).with_name("static")
NIVEAUX = {"lecteur": 0, "gestionnaire": 1, "admin": 2}


def _nom_fichier(t: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", t).strip("_") or "document"


def creer_app(dossier: str | Path | None = None) -> FastAPI:
    st = Stockage(dossier or os.environ.get("KOORDINPAIE_DONNEES", "donnees_koordinpaie"))

    @asynccontextmanager
    async def cycle(_app):
        yield
        st.fermer()   # base fermée à l'arrêt du serveur

    app = FastAPI(title="Koordin Paie", version="0.1", lifespan=cycle)
    app.state.stockage = st

    @app.exception_handler(ValueError)
    def _erreur_valeur(_req, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(LookupError)
    def _erreur_absent(_req, exc: LookupError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    # ------------------------------------------------------------------ droits
    def utilisateur(request: Request) -> dict:
        u = st.utilisateur_session(request.cookies.get(COOKIE))
        if not u:
            raise HTTPException(401, "Connexion requise.")
        return u

    def gestionnaire(u: dict = Depends(utilisateur)) -> dict:
        if NIVEAUX[u["role"]] < NIVEAUX["gestionnaire"]:
            raise HTTPException(403, "Droits insuffisants : accès en lecture seule.")
        return u

    def admin(u: dict = Depends(utilisateur)) -> dict:
        if u["role"] != "admin":
            raise HTTPException(403, "Réservé aux administrateurs.")
        return u

    async def corps(request: Request) -> dict:
        try:
            d = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Données JSON invalides.") from None
        if not isinstance(d, dict):
            raise HTTPException(400, "Données JSON invalides.")
        return d

    def trouver(obj, quoi: str):
        if not obj:
            raise HTTPException(404, f"{quoi} introuvable.")
        return obj

    def pdf(contenu: bytes, nom: str) -> Response:
        return Response(contenu, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{_nom_fichier(nom)}.pdf"'})

    # ------------------------------------------------------------------ comptes
    @app.get("/api/etat")
    def etat(request: Request):
        return {"premier_compte": st.nb_utilisateurs() == 0,
                "utilisateur": st.utilisateur_session(request.cookies.get(COOKIE))}

    def _connecter(uid: int, request: Request) -> JSONResponse:
        rep = JSONResponse({"ok": True})
        rep.set_cookie(COOKIE, st.nouvelle_session(uid), httponly=True, samesite="lax",
                       secure=request.url.scheme == "https", max_age=14 * 86400)
        return rep

    @app.post("/api/inscription")
    async def inscription(request: Request):
        d = await corps(request)
        if st.nb_utilisateurs():
            raise HTTPException(403, "Les comptes sont créés par un administrateur.")
        uid = st.creer_utilisateur(d.get("email", ""), d.get("nom", ""), d.get("mdp", ""), "admin")
        st.journaliser(uid, "Création du compte administrateur")
        return _connecter(uid, request)

    @app.post("/api/connexion")
    async def connexion(request: Request):
        d = await corps(request)
        u = st.authentifier(d.get("email", ""), d.get("mdp", ""))
        if not u:
            raise HTTPException(401, "Adresse ou mot de passe incorrect.")
        return _connecter(u["id"], request)

    @app.post("/api/deconnexion")
    def deconnexion(request: Request):
        if request.cookies.get(COOKIE):
            st.fin_session(request.cookies[COOKIE])
        rep = JSONResponse({"ok": True})
        rep.delete_cookie(COOKIE)
        return rep

    @app.get("/api/utilisateurs")
    def utilisateurs(_u=Depends(admin)):
        return st.utilisateurs()

    @app.post("/api/utilisateurs")
    async def creer_utilisateur(request: Request, u=Depends(admin)):
        d = await corps(request)
        uid = st.creer_utilisateur(d.get("email", ""), d.get("nom", ""), d.get("mdp", ""),
                                   d.get("role", "gestionnaire"))
        st.journaliser(u["id"], f"Compte créé : {d.get('email')} ({d.get('role', 'gestionnaire')})")
        return {"id": uid}

    @app.put("/api/utilisateurs/{uid}")
    async def modifier_utilisateur(uid: int, request: Request, u=Depends(admin)):
        d = await corps(request)
        st.modifier_utilisateur(uid, d.get("role"), d.get("mdp"))
        return {"ok": True}

    @app.delete("/api/utilisateurs/{uid}")
    def supprimer_utilisateur(uid: int, u=Depends(admin)):
        if uid == u["id"]:
            raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte.")
        st.supprimer_utilisateur(uid)
        return {"ok": True}

    @app.put("/api/moi/mdp")
    async def changer_mdp(request: Request, u=Depends(utilisateur)):
        d = await corps(request)
        if not st.authentifier(u["email"], d.get("ancien", "")):
            raise HTTPException(400, "Mot de passe actuel incorrect.")
        st.modifier_utilisateur(u["id"], mdp=d.get("nouveau", ""))
        return _connecter(u["id"], request)

    # ------------------------------------------------------------------ réglages
    @app.get("/api/entreprise")
    def lire_entreprise(_u=Depends(utilisateur)):
        return paie.entreprise(st)

    @app.put("/api/entreprise")
    async def ecrire_entreprise(request: Request, u=Depends(gestionnaire)):
        st.regler("entreprise", await corps(request))
        st.journaliser(u["id"], "Fiche entreprise modifiée")
        return {"ok": True}

    @app.get("/api/bareme")
    def lire_bareme(_u=Depends(utilisateur)):
        return {"bareme": paie.bareme(st), "defaut": charger_bareme(), "modifie": bool(st.reglage("bareme"))}

    @app.put("/api/bareme")
    async def ecrire_bareme(request: Request, u=Depends(admin)):
        d = await corps(request)
        defaut = charger_bareme()
        if set(d) - set(defaut):
            raise HTTPException(400, f"Rubriques inconnues : {', '.join(sorted(set(d) - set(defaut)))}")
        st.regler("bareme", d)
        try:
            paie.bareme(st)["its"]["tranches"][0][1]  # contrôle de forme
        except Exception:  # noqa: BLE001
            st.regler("bareme", {})
            raise HTTPException(400, "Barème invalide.") from None
        st.journaliser(u["id"], "Barème de paie modifié")
        return {"ok": True}

    @app.delete("/api/bareme")
    def reinit_bareme(u=Depends(admin)):
        st.regler("bareme", {})
        st.journaliser(u["id"], f"Barème de paie rétabli ({BAREME_DEFAUT.name})")
        return {"ok": True}

    @app.get("/api/journal")
    def journal(_u=Depends(utilisateur)):
        return st.journal()

    # ------------------------------------------------------------------ salariés
    def _resume_salarie(s: dict) -> dict:
        contrats = st.contrats(s["id"])
        en_cours = next((c for c in contrats if c.get("statut") != "termine"), None)
        if en_cours:
            en_cours = st.contrat_au(en_cours["id"], date.today().isoformat())
        s["contrat"] = en_cours
        s["nb_contrats"] = len(contrats)
        return s

    @app.get("/api/salaries")
    def salaries(_u=Depends(utilisateur)):
        return [_resume_salarie(s) for s in st.salaries()]

    @app.post("/api/salaries")
    async def creer_salarie(request: Request, u=Depends(gestionnaire)):
        d = await corps(request)
        sid = st.enregistrer_salarie(d)
        st.journaliser(u["id"], f"Salarié ajouté : {d.get('nom')} {d.get('prenoms', '')}")
        return {"id": sid}

    @app.get("/api/salaries/{sid}")
    def lire_salarie(sid: int, _u=Depends(utilisateur)):
        s = trouver(st.salarie(sid), "Salarié")
        s["contrats"] = []
        for c in st.contrats(sid):
            c["avenants"] = st.avenants(c["id"])
            s["contrats"].append(c)
        s["date_embauche_effective"] = paie.date_embauche(st, s)
        s["bulletins"] = st.q("SELECT b.id, p.annee, p.mois, p.statut FROM bulletins b JOIN periodes p "
                              "ON p.id=b.periode_id WHERE b.salarie_id=? ORDER BY p.annee DESC, p.mois DESC", (sid,))
        return s

    @app.put("/api/salaries/{sid}")
    async def modifier_salarie(sid: int, request: Request, u=Depends(gestionnaire)):
        trouver(st.salarie(sid), "Salarié")
        d = await corps(request)
        st.enregistrer_salarie(d, sid)
        st.journaliser(u["id"], f"Fiche salarié modifiée : {d.get('nom')} {d.get('prenoms', '')}")
        return {"ok": True}

    @app.delete("/api/salaries/{sid}")
    def supprimer_salarie(sid: int, u=Depends(gestionnaire)):
        s = trouver(st.salarie(sid), "Salarié")
        st.supprimer_salarie(sid)
        st.journaliser(u["id"], f"Salarié supprimé : {s['nom']} {s.get('prenoms', '')}")
        return {"ok": True}

    # ------------------------------------------------------------------ contrats
    @app.post("/api/salaries/{sid}/contrats")
    async def creer_contrat(sid: int, request: Request, u=Depends(gestionnaire)):
        s = trouver(st.salarie(sid), "Salarié")
        d = await corps(request)
        cid = st.enregistrer_contrat(sid, d)
        st.journaliser(u["id"], f"Contrat {d.get('type', 'CDI')} créé pour {s['nom']} {s.get('prenoms', '')}")
        return {"id": cid}

    @app.put("/api/contrats/{cid}")
    async def modifier_contrat(cid: int, request: Request, u=Depends(gestionnaire)):
        c = trouver(st.contrat(cid), "Contrat")
        st.enregistrer_contrat(c["salarie_id"], await corps(request), cid)
        st.journaliser(u["id"], f"Contrat n° {cid} modifié")
        return {"ok": True}

    @app.delete("/api/contrats/{cid}")
    def supprimer_contrat(cid: int, u=Depends(gestionnaire)):
        trouver(st.contrat(cid), "Contrat")
        st.supprimer_contrat(cid)
        st.journaliser(u["id"], f"Contrat n° {cid} supprimé")
        return {"ok": True}

    @app.post("/api/contrats/{cid}/fin")
    async def terminer_contrat(cid: int, request: Request, u=Depends(gestionnaire)):
        trouver(st.contrat(cid), "Contrat")
        d = await corps(request)
        if not d.get("date_fin"):
            raise HTTPException(400, "La date de fin est obligatoire.")
        st.terminer_contrat(cid, d["date_fin"], d.get("motif", ""))
        st.journaliser(u["id"], f"Fin du contrat n° {cid} au {d['date_fin']} ({d.get('motif', '')})")
        return {"ok": True}

    @app.post("/api/contrats/{cid}/avenants")
    async def ajouter_avenant(cid: int, request: Request, u=Depends(gestionnaire)):
        trouver(st.contrat(cid), "Contrat")
        d = await corps(request)
        if not d.get("date_effet"):
            raise HTTPException(400, "La date d'effet est obligatoire.")
        aid = st.ajouter_avenant(cid, d["date_effet"], d.get("objet", ""), d.get("modifications") or {})
        st.journaliser(u["id"], f"Avenant au contrat n° {cid} : {d.get('objet', '')}")
        return {"id": aid}

    @app.delete("/api/avenants/{aid}")
    def supprimer_avenant(aid: int, u=Depends(gestionnaire)):
        st.supprimer_avenant(aid)
        st.journaliser(u["id"], f"Avenant n° {aid} supprimé")
        return {"ok": True}

    @app.get("/api/contrats/{cid}/pdf")
    def contrat_pdf(cid: int, _u=Depends(utilisateur)):
        c = trouver(st.contrat(cid), "Contrat")
        s = st.salarie(c["salarie_id"])
        contenu = documents.contrat_pdf(c, s, paie.entreprise(st), st.avenants(cid))
        return pdf(contenu, f"contrat_{c['type']}_{s['matricule']}_{s['nom']}")

    @app.get("/api/alertes")
    def alertes(_u=Depends(utilisateur)):
        return paie.alertes(st)

    # ------------------------------------------------------------------ paie
    @app.get("/api/periodes")
    def periodes(_u=Depends(utilisateur)):
        out = []
        for p in st.periodes():
            p["libelle"] = paie.libelle_periode(p["annee"], p["mois"])
            p["nb_bulletins"] = st.q("SELECT COUNT(*) n FROM bulletins WHERE periode_id=?", (p["id"],), un=True)["n"]
            out.append(p)
        return out

    @app.post("/api/periodes")
    async def creer_periode(request: Request, u=Depends(gestionnaire)):
        d = await corps(request)
        pid = st.creer_periode(int(d.get("annee", 0)), int(d.get("mois", 0)))
        paie.synchroniser(st, pid)
        st.journaliser(u["id"], f"Paie ouverte : {paie.libelle_periode(int(d['annee']), int(d['mois']))}")
        return {"id": pid}

    @app.get("/api/periodes/{pid}")
    def lire_periode(pid: int, _u=Depends(utilisateur)):
        trouver(st.periode(pid), "Période")
        return paie.periode_complete(st, pid)

    @app.delete("/api/periodes/{pid}")
    def supprimer_periode(pid: int, u=Depends(gestionnaire)):
        p = trouver(st.periode(pid), "Période")
        st.supprimer_periode(pid)
        st.journaliser(u["id"], f"Paie supprimée : {paie.libelle_periode(p['annee'], p['mois'])}")
        return {"ok": True}

    @app.post("/api/periodes/{pid}/cloture")
    def cloturer(pid: int, u=Depends(gestionnaire)):
        p = trouver(st.periode(pid), "Période")
        paie.cloturer(st, pid)
        st.journaliser(u["id"], f"Paie clôturée : {paie.libelle_periode(p['annee'], p['mois'])}")
        return {"ok": True}

    @app.post("/api/periodes/{pid}/reouverture")
    def rouvrir(pid: int, u=Depends(admin)):
        p = trouver(st.periode(pid), "Période")
        paie.rouvrir(st, pid)
        st.journaliser(u["id"], f"Paie rouverte : {paie.libelle_periode(p['annee'], p['mois'])}")
        return {"ok": True}

    @app.get("/api/periodes/{pid}/bulletins.pdf")
    def bulletins_pdf(pid: int, _u=Depends(utilisateur)):
        p = trouver(st.periode(pid), "Période")
        per = paie.periode_complete(st, pid)
        if not per["bulletins"]:
            raise HTTPException(404, "Aucun bulletin pour cette période.")
        contenu = documents.assembler([documents.bulletin_pdf(paie.bulletin_complet(st, b["id"]))
                                       for b in per["bulletins"]])
        return pdf(contenu, f"bulletins_{p['annee']}-{p['mois']:02d}")

    @app.get("/api/periodes/{pid}/livre.xlsx")
    def livre(pid: int, _u=Depends(utilisateur)):
        p = trouver(st.periode(pid), "Période")
        contenu = documents.livre_xlsx(paie.periode_complete(st, pid), paie.entreprise(st))
        nom = f"livre_de_paie_{p['annee']}-{p['mois']:02d}.xlsx"
        return Response(contenu, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    @app.get("/api/bulletins/{bid}")
    def lire_bulletin(bid: int, _u=Depends(utilisateur)):
        trouver(st.bulletin(bid), "Bulletin")
        return paie.bulletin_complet(st, bid)

    @app.put("/api/bulletins/{bid}")
    async def modifier_bulletin(bid: int, request: Request, u=Depends(gestionnaire)):
        b = trouver(st.bulletin(bid), "Bulletin")
        if st.periode(b["periode_id"])["statut"] != "ouverte":
            raise HTTPException(400, "La période est clôturée : rouvrez-la pour modifier ce bulletin.")
        d = await corps(request)
        st.modifier_variables(bid, d.get("variables", d))
        return paie.bulletin_complet(st, bid)

    @app.get("/api/bulletins/{bid}/pdf")
    def bulletin_pdf(bid: int, _u=Depends(utilisateur)):
        trouver(st.bulletin(bid), "Bulletin")
        b = paie.bulletin_complet(st, bid)
        s, p = b["instantane"]["salarie"], b["periode"]
        return pdf(documents.bulletin_pdf(b), f"bulletin_{p['annee']}-{p['mois']:02d}_{s['matricule']}_{s['nom']}")

    @app.post("/api/simulation")
    async def simulation(request: Request, _u=Depends(utilisateur)):
        d = await corps(request)
        try:
            return calculer_dict(d.get("salarie") or {}, d.get("contrat") or {}, d.get("variables") or {},
                                 int(d.get("annee", 2026)), int(d.get("mois", 1)), paie.bareme(st),
                                 float(d["taux_at"]) / 100 if d.get("taux_at") not in (None, "") else None)
        except (TypeError, KeyError) as exc:
            raise HTTPException(400, f"Données incomplètes : {exc}") from None

    # ------------------------------------------------------------------ interface
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def accueil():
        return FileResponse(STATIC / "index.html")

    app.state.roles = ROLES
    return app
