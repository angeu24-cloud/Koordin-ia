"""Application web BatiCalc : API (FastAPI) + interface (fichiers statiques).

Lancement : baticalc serveur --port 8000 --donnees ./donnees
"""
from __future__ import annotations

import contextlib
import io
import hmac
import json
import os
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .storage import ROLES, Storage

STATIC = Path(__file__).parent / "static"
COOKIE = "baticalc_session"
MAX_UPLOAD = 200 * 1024 * 1024
PLAN_EXT = {".dwg", ".dxf", ".pdf", ".ifc", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
REPORT_EXT = {".pdf", ".txt", ".docx"}
BPU_EXT = {".xls", ".xlsx", ".xlsm", ".csv"}
SAFE_NAME = re.compile(r"^[\w\-. ]{1,120}$")


def _safe_filename(name: str) -> str:
    base = Path(name or "fichier").name
    base = re.sub(r"[^\w\-. ]", "_", base)[:120] or "fichier"
    return base


def create_app(data_dir: str | Path | None = None, sync_jobs: bool | None = None,
               inscription: str | None = None, code_inscription: str | None = None) -> FastAPI:
    """Inscriptions :
    - `inscription` « ouverte » (défaut) : tout visiteur peut créer un compte ;
    - « fermee » : seul le premier compte (administrateur) peut être créé ;
    - `code_inscription` : code d'invitation exigé pour créer un compte (sauf le premier).
    Variables d'environnement équivalentes : BATICALC_INSCRIPTION, BATICALC_CODE_INSCRIPTION."""
    from .. import data_dir as _data_dir, env

    store = Storage(data_dir or _data_dir(env("DATA", "donnees_baticalc")))
    sync = sync_jobs if sync_jobs is not None else env("SYNC_JOBS") == "1"
    signup_mode = (inscription or env("INSCRIPTION", "ouverte")).lower()
    signup_code = code_inscription if code_inscription is not None else env("CODE_INSCRIPTION")
    pool = ThreadPoolExecutor(max_workers=1)
    run_lock = threading.Lock()
    app = FastAPI(title="BatiCalc", version="0.2")
    app.state.store = store

    # ------------------------------------------------------------------ dépendances
    def current_user(request: Request) -> dict:
        u = store.session_user(request.cookies.get(COOKIE))
        if not u:
            raise HTTPException(401, "Connexion requise.")
        return u

    def project_access(pid: int, user: dict, need: str = "lecteur") -> dict:
        p = store.project(pid)
        role = store.role(pid, user["id"]) if p else None
        if not p or not role:
            raise HTTPException(404, "Projet introuvable.")
        if ROLES.index(role) > ROLES.index(need):
            raise HTTPException(403, "Droits insuffisants pour cette action.")
        p["role"] = role
        return p

    def cfg_path(pid: int) -> Path:
        path = store.project_dir(pid) / "baticalc.json"
        old = path.with_name("koordinia.json")   # projet créé sous l'ancien nom
        if not path.exists() and old.exists():
            old.rename(path)
        return path

    def read_cfg(pid: int) -> dict:
        from ..cli import CONFIG_TEMPLATE

        path = cfg_path(pid)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        cfg = json.loads(json.dumps(CONFIG_TEMPLATE))
        cfg["projet"]["nom"] = store.project(pid)["name"]
        cfg["projet"]["plan"] = None
        cfg["projet"]["sortie"] = "resultats"
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return cfg

    def write_cfg(pid: int, cfg: dict) -> None:
        cfg_path(pid).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------ tâches
    def submit(pid: int, kind: str, user_id: int, fn) -> int:
        jid = store.new_job(pid, kind, user_id)

        def work():
            store.update_job(jid, "en_cours")
            buf = io.StringIO()
            try:
                with run_lock, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    fn()
                store.update_job(jid, "termine", buf.getvalue()[-20000:])
                store.touch(pid, {"analyse": "plan analysé", "calcul": "calculé"}.get(kind))
                store.log(pid, user_id, {"analyse": "Analyse du plan terminée",
                                         "calcul": "Calcul terminé"}.get(kind, kind))
            except Exception as exc:  # noqa: BLE001 — l'erreur est rendue à l'utilisateur
                store.update_job(jid, "erreur", buf.getvalue()[-20000:], f"{exc}\n{traceback.format_exc()[-3000:]}")
                store.log(pid, user_id, f"Échec : {kind} — {exc}")

        if sync:
            work()
        else:
            pool.submit(work)
        return jid

    def analyse(pid: int) -> None:
        from ..importers import import_plan
        from ..levels import display_name
        from ..project import candidate_resolver, plan_storeys, resolve_candidates
        from ..sheets import find_sheets

        cfg = read_cfg(pid)
        plan = store.project_dir(pid) / cfg["projet"]["plan"]
        lec = cfg.get("lecture", {})
        if plan.suffix.lower() == ".ifc":
            from ..interop.ifc_import import import_ifc

            pj = import_ifc(plan)
            z = 0.0
            out = {"fichier": plan.name, "planches": [], "niveaux": [], "notes": pj.warnings, "multi": True,
                   "ifc": True}
            for st in pj.storeys:
                out["niveaux"].append({"nom": st.name, "code": st.name, "altitude": round(z, 2), "hauteur": st.height,
                                       "planche": None, "titre": "IFC", "raison": f"{len(st.plan.columns)} poteaux"})
                z += st.height
            (store.project_dir(pid) / "analyse.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
            print(f"Modèle IFC lu : {len(pj.storeys)} étage(s).")
            return
        drawing = import_plan(plan, units=lec.get("unites"), scale=lec.get("echelle"),
                              px_per_m=lec.get("echelle_px_m"))
        sheets = find_sheets(drawing)
        out = {"fichier": plan.name, "planches": [
            {"numero": s.index, "titre": s.title, "plan": s.is_plan,
             "taille": [round(s.bbox[2] - s.bbox[0], 1), round(s.bbox[3] - s.bbox[1], 1)]} for s in sheets],
            "niveaux": [], "notes": list(drawing.warnings), "multi": False}
        if sum(s.is_plan for s in sheets) >= 1:
            try:
                storeys, _, notes = plan_storeys(drawing, default_height=float(lec.get("hauteur") or 3.0))
                notes += resolve_candidates(storeys, sheets, *candidate_resolver(drawing, lec.get("calque_poteaux")))
                z = 0.0
                for sp in storeys:
                    out["niveaux"].append({"nom": display_name(sp.name), "code": sp.name, "altitude": round(z, 2),
                                           "hauteur": sp.height, "planche": sp.sheet.index if sp.sheet else None,
                                           "titre": sp.sheet.title if sp.sheet else "", "raison": sp.reason})
                    z += sp.height
                out["notes"] += notes
                out["multi"] = len(storeys) >= 2
            except ValueError as exc:
                out["notes"].append(str(exc))
        (store.project_dir(pid) / "analyse.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
        cfg["projet"]["tous_niveaux"] = out["multi"]
        if not out["multi"] and sum(s.is_plan for s in sheets) > 1 and not lec.get("planche"):
            first = next(s for s in sheets if s.is_plan)
            cfg.setdefault("lecture", {})["planche"] = str(first.index)
        write_cfg(pid, cfg)
        print(f"Plan analysé : {len(sheets)} planche(s), {len(out['niveaux'])} niveau(x).")

    def calcul(pid: int) -> None:
        from ..cli import main

        rc = main(["calculer", "--config", str(cfg_path(pid))])
        if rc != 0:
            raise RuntimeError("le calcul a échoué (voir le journal)")

    # ------------------------------------------------------------------ comptes
    def signup_rules() -> dict:
        first = store.q("SELECT COUNT(*) AS n FROM users", one=True)["n"] == 0
        closed = signup_mode.startswith("ferm") and not signup_code
        return {"ouverte": first or not closed, "code": bool(signup_code) and not first, "premier": first}

    @app.get("/api/compte/inscription")
    def register_rules():
        return signup_rules()

    @app.post("/api/compte/inscription")
    def register(body: dict, request: Request, response: Response):
        rules = signup_rules()
        if not rules["ouverte"]:
            raise HTTPException(403, "Les inscriptions sont fermées : demandez un compte à l'administrateur.")
        if rules["code"] and not hmac.compare_digest(str(body.get("code", "")), str(signup_code)):
            raise HTTPException(403, "Code d'invitation incorrect.")
        email, name, pw = body.get("email", ""), body.get("nom", ""), body.get("mot_de_passe", "")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""):
            raise HTTPException(400, "Adresse e-mail invalide.")
        if len(pw) < 8:
            raise HTTPException(400, "Mot de passe : 8 caractères minimum.")
        if not name.strip():
            raise HTTPException(400, "Indiquez votre nom.")
        try:
            uid = store.create_user(email, name, pw)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        response.set_cookie(COOKIE, store.new_session(uid), httponly=True, samesite="lax", max_age=14 * 86400,
                            secure=request.url.scheme == "https")
        return {"id": uid, "email": email.lower(), "nom": name}

    @app.post("/api/compte/connexion")
    def login(body: dict, request: Request, response: Response):
        u = store.authenticate(body.get("email", ""), body.get("mot_de_passe", ""))
        if not u:
            raise HTTPException(401, "Adresse ou mot de passe incorrect.")
        response.set_cookie(COOKIE, store.new_session(u["id"]), httponly=True, samesite="lax", max_age=14 * 86400,
                            secure=request.url.scheme == "https")
        return {"id": u["id"], "email": u["email"], "nom": u["name"]}

    @app.post("/api/compte/deconnexion")
    def logout(request: Request, response: Response):
        tok = request.cookies.get(COOKIE)
        if tok:
            store.end_session(tok)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/compte")
    def me(user: dict = Depends(current_user)):
        return {"id": user["id"], "email": user["email"], "nom": user["name"]}

    # ------------------------------------------------------------------ projets
    @app.get("/api/projets")
    def list_projects(user: dict = Depends(current_user)):
        return [{"id": p["id"], "nom": p["name"], "role": p["role"], "proprietaire": p["owner_name"],
                 "statut": p["status"], "modifie": p["updated"]} for p in store.projects_for(user["id"])]

    @app.post("/api/projets")
    def create_project(body: dict, user: dict = Depends(current_user)):
        name = (body.get("nom") or "").strip()
        if not name:
            raise HTTPException(400, "Nom du projet requis.")
        pid = store.create_project(name, user["id"])
        read_cfg(pid)
        store.log(pid, user["id"], f"Projet créé : {name}")
        return {"id": pid, "nom": name}

    @app.get("/api/projets/{pid}")
    def get_project(pid: int, user: dict = Depends(current_user)):
        p = project_access(pid, user)
        d = store.project_dir(pid)
        res_dir = d / "resultats"
        summary = None
        if (res_dir / "resultats.json").exists():
            r = json.loads((res_dir / "resultats.json").read_text(encoding="utf-8"))
            summary = {k: r.get(k) for k in ("norme", "niveaux", "metre", "fondations", "avertissements")}
            summary["n_poteaux"] = len(r.get("poteaux", []))
            summary["n_poutres"] = len(r.get("poutres", []))
            summary["n_semelles"] = len(r.get("semelles", []))
            summary["non_verifies"] = sum(not x.get("ok", True) for k in ("poteaux", "poutres", "semelles")
                                          for x in r.get(k, []))
        files = sorted(f.name for f in res_dir.iterdir() if f.is_file()) if res_dir.exists() else []
        geo = json.loads((d / "geotech.json").read_text(encoding="utf-8")) if (d / "geotech.json").exists() else None
        analyse_d = json.loads((d / "analyse.json").read_text(encoding="utf-8")) if (d / "analyse.json").exists() \
            else None
        return {
            "id": pid, "nom": p["name"], "role": p["role"], "statut": p["status"], "modifie": p["updated"],
            "configuration": read_cfg(pid), "analyse": analyse_d, "geotech": geo, "resultats": summary,
            "fichiers": files, "membres": store.members(pid), "journal": store.activity(pid),
            "tache": store.last_job(pid),
        }

    @app.patch("/api/projets/{pid}")
    def rename(pid: int, body: dict, user: dict = Depends(current_user)):
        project_access(pid, user, "proprietaire")
        name = (body.get("nom") or "").strip()
        if not name:
            raise HTTPException(400, "Nom requis.")
        store.rename_project(pid, name)
        cfg = read_cfg(pid)
        cfg["projet"]["nom"] = name
        write_cfg(pid, cfg)
        return {"ok": True}

    @app.delete("/api/projets/{pid}")
    def delete(pid: int, user: dict = Depends(current_user)):
        project_access(pid, user, "proprietaire")
        store.delete_project(pid)
        return {"ok": True}

    # ------------------------------------------------------------------ équipe
    @app.post("/api/projets/{pid}/membres")
    def add_member(pid: int, body: dict, user: dict = Depends(current_user)):
        project_access(pid, user, "proprietaire")
        try:
            u = store.set_member(pid, body.get("email", ""), body.get("role", "editeur"))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.log(pid, user["id"], f"{u['name']} ajouté(e) à l'équipe ({body.get('role', 'editeur')})")
        return store.members(pid)

    @app.delete("/api/projets/{pid}/membres/{uid}")
    def remove_member(pid: int, uid: int, user: dict = Depends(current_user)):
        project_access(pid, user, "proprietaire")
        try:
            store.remove_member(pid, uid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.members(pid)

    # ------------------------------------------------------------------ plan, hypothèses, géotechnique
    async def save_upload(pid: int, up: UploadFile, sub: str, allowed: set[str]) -> Path:
        name = _safe_filename(up.filename)
        ext = Path(name).suffix.lower()
        data = await up.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Fichier trop volumineux (200 Mo maximum).")
        if ext not in allowed and not (data[:4] == b"AC10" and ".dwg" in allowed):
            raise HTTPException(400, f"Format non accepté ({', '.join(sorted(allowed))}).")
        if data[:4] == b"AC10" and ext != ".dwg":
            name += ".dwg"
        folder = store.project_dir(pid) / sub
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(data)
        return path

    @app.post("/api/projets/{pid}/plan")
    async def upload_plan(pid: int, fichier: UploadFile = File(...), user: dict = Depends(current_user)):
        project_access(pid, user, "editeur")
        path = await save_upload(pid, fichier, "plans", PLAN_EXT)
        cfg = read_cfg(pid)
        cfg["projet"]["plan"] = f"plans/{path.name}"
        cfg.setdefault("lecture", {})["planche"] = None
        write_cfg(pid, cfg)
        store.log(pid, user["id"], f"Plan importé : {path.name}")
        jid = submit(pid, "analyse", user["id"], lambda: analyse(pid))
        return {"tache": jid, "fichier": path.name}

    @app.post("/api/projets/{pid}/analyse")
    def reanalyse(pid: int, user: dict = Depends(current_user)):
        project_access(pid, user, "editeur")
        if not read_cfg(pid)["projet"].get("plan"):
            raise HTTPException(400, "Importez d'abord un plan.")
        return {"tache": submit(pid, "analyse", user["id"], lambda: analyse(pid))}

    @app.put("/api/projets/{pid}/configuration")
    def put_config(pid: int, body: dict, user: dict = Depends(current_user)):
        project_access(pid, user, "editeur")
        cfg = read_cfg(pid)
        for section in ("lecture", "reglement", "charges", "sol", "usages", "projet", "devis"):
            if isinstance(body.get(section), dict):
                cur = cfg.setdefault(section, {})
                for k, v in body[section].items():
                    if section == "projet" and k not in ("tous_niveaux",):
                        continue  # chemins gérés par le serveur
                    if section == "devis" and k == "bpu":
                        continue
                    cur[k] = v
        write_cfg(pid, cfg)
        store.touch(pid)
        store.log(pid, user["id"], "Hypothèses modifiées")
        return cfg

    @app.post("/api/projets/{pid}/geotech")
    async def upload_report(pid: int, fichier: UploadFile = File(...), user: dict = Depends(current_user)):
        from ..geotech import extract

        project_access(pid, user, "editeur")
        path = await save_upload(pid, fichier, "geotech", REPORT_EXT)
        try:
            g = extract(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        g.fichier = path.name
        g.save(store.project_dir(pid) / "geotech.json")
        cfg = read_cfg(pid)
        cfg.setdefault("sol", {})["geotech"] = "geotech.json"
        write_cfg(pid, cfg)
        store.log(pid, user["id"], f"Rapport géotechnique lu : {path.name} (à valider)")
        return g.to_dict()

    @app.put("/api/projets/{pid}/geotech")
    def put_geotech(pid: int, body: dict, user: dict = Depends(current_user)):
        from ..geotech import GeotechData

        project_access(pid, user, "editeur")
        g = GeotechData.from_dict(body)
        g.save(store.project_dir(pid) / "geotech.json")
        cfg = read_cfg(pid)
        cfg.setdefault("sol", {})["geotech"] = "geotech.json"
        write_cfg(pid, cfg)
        store.log(pid, user["id"], "Données géotechniques " + ("validées" if g.valide else "modifiées"))
        return g.to_dict()

    @app.post("/api/projets/{pid}/bpu")
    async def upload_bpu(pid: int, fichier: UploadFile = File(...), user: dict = Depends(current_user)):
        from ..costing.bpu import import_bpu

        project_access(pid, user, "editeur")
        path = await save_upload(pid, fichier, "prix", BPU_EXT)
        try:
            b = import_bpu(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        b.save(store.project_dir(pid) / "bpu.json")
        cfg = read_cfg(pid)
        cfg.setdefault("devis", {})["bpu"] = "bpu.json"
        write_cfg(pid, cfg)
        store.log(pid, user["id"], f"Bordereau de prix importé : {path.name} ({len(b.items)} articles)")
        return {"source": b.source, "articles": len(b.items), "notes": b.notes}

    @app.get("/api/projets/{pid}/devis")
    def get_devis(pid: int, user: dict = Depends(current_user)):
        project_access(pid, user)
        d = store.project_dir(pid)
        out = {"devis": None, "bordereau": None}
        if (d / "resultats" / "devis.json").exists():
            out["devis"] = json.loads((d / "resultats" / "devis.json").read_text(encoding="utf-8"))
        if (d / "bpu.json").exists():
            b = json.loads((d / "bpu.json").read_text(encoding="utf-8"))
            out["bordereau"] = {"source": b.get("source"), "articles": len(b.get("items", [])), "notes": b.get("notes")}
        return out

    # ------------------------------------------------------------------ calcul et résultats
    @app.post("/api/projets/{pid}/calcul")
    def run_calc(pid: int, user: dict = Depends(current_user)):
        project_access(pid, user, "editeur")
        if not read_cfg(pid)["projet"].get("plan"):
            raise HTTPException(400, "Importez d'abord un plan.")
        store.log(pid, user["id"], "Calcul lancé")
        return {"tache": submit(pid, "calcul", user["id"], lambda: calcul(pid))}

    @app.get("/api/taches/{jid}")
    def get_job(jid: int, user: dict = Depends(current_user)):
        j = store.job(jid)
        if not j:
            raise HTTPException(404, "Tâche introuvable.")
        project_access(j["project_id"], user)
        return j

    @app.get("/api/projets/{pid}/modele")
    def get_model(pid: int, user: dict = Depends(current_user)):
        project_access(pid, user)
        path = store.project_dir(pid) / "resultats" / "modele_3d.json"
        if not path.exists():
            raise HTTPException(404, "Aucun calcul : lancez le calcul du projet.")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/projets/{pid}/fichiers/{name}")
    def get_file(pid: int, name: str, user: dict = Depends(current_user)):
        project_access(pid, user)
        if not SAFE_NAME.match(name) or ".." in name:
            raise HTTPException(400, "Nom de fichier invalide.")
        path = store.project_dir(pid) / "resultats" / name
        if not path.is_file():
            raise HTTPException(404, "Fichier introuvable.")
        return FileResponse(path, filename=name)

    # ------------------------------------------------------------------ interface
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    return app
