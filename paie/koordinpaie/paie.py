"""Préparation, calcul et clôture des paies mensuelles ; alertes sur les contrats."""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta

from .calcul import calculer_dict, charger_bareme, prorata_mois
from .stockage import Stockage

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")


def libelle_periode(annee: int, mois: int) -> str:
    return f"{MOIS[mois - 1]} {annee}"


def bornes(annee: int, mois: int) -> tuple[str, str]:
    return f"{annee:04d}-{mois:02d}-01", f"{annee:04d}-{mois:02d}-{calendar.monthrange(annee, mois)[1]:02d}"


def bareme(st: Stockage) -> dict:
    return charger_bareme(st.reglage("bareme", {}))


def entreprise(st: Stockage) -> dict:
    return st.reglage("entreprise", {}) or {}


def date_embauche(st: Stockage, salarie: dict) -> str:
    if salarie.get("date_embauche"):
        return salarie["date_embauche"]
    debuts = [c["date_debut"] for c in st.contrats(salarie["id"])]
    return min(debuts) if debuts else date.today().isoformat()


def contrats_du_mois(st: Stockage, annee: int, mois: int) -> list[dict]:
    d0, d1 = bornes(annee, mois)
    return [c for c in st.contrats() if c["date_debut"] <= d1 and (not c["date_fin"] or c["date_fin"] >= d0)
            and c.get("statut") != "brouillon"]


def synchroniser(st: Stockage, pid: int) -> None:
    """Période ouverte : un bulletin par contrat en cours dans le mois (ajouts et retraits)."""
    p = st.periode(pid)
    if not p or p["statut"] != "ouverte":
        return
    contrats = {c["id"]: c for c in contrats_du_mois(st, p["annee"], p["mois"])}
    existants = {b["contrat_id"]: b for b in st.bulletins(pid)}
    for cid, b in existants.items():
        if cid not in contrats:
            st.supprimer_bulletin(b["id"])
    for cid, c in contrats.items():
        if cid not in existants:
            s = st.salarie(c["salarie_id"])
            if s and s.get("actif", True):
                st.ajouter_bulletin(pid, c["salarie_id"], cid, {})


def _cumul_brut_contrat(st: Stockage, cid: int, avant: tuple[int, int]) -> int:
    total = 0
    for r in st.q("SELECT b.resultat, p.annee, p.mois FROM bulletins b JOIN periodes p ON p.id=b.periode_id "
                  "WHERE b.contrat_id=? AND p.statut='cloturee'", (cid,)):
        if (r["annee"], r["mois"]) < avant and r["resultat"]:
            total += json.loads(r["resultat"])["brut"]
    return total


def calculer_bulletin(st: Stockage, b: dict, p: dict, bar: dict | None = None) -> tuple[dict, dict]:
    """(résultat, instantané des données utilisées) pour un bulletin."""
    bar = bar or bareme(st)
    ent = entreprise(st)
    annee, mois = p["annee"], p["mois"]
    d0, d1 = bornes(annee, mois)
    s = st.salarie(b["salarie_id"])
    s["date_embauche"] = date_embauche(st, s)
    c = st.contrat_au(b["contrat_id"], d1)
    var = dict(b["variables"])
    if c.get("mode", "mensuel") == "mensuel" and var.get("prorata") in (None, ""):
        var["prorata"] = prorata_mois(annee, mois, date.fromisoformat(c["date_debut"]),
                                      date.fromisoformat(c["date_fin"]) if c.get("date_fin") else None)
    at = ent.get("taux_at")
    at = float(at) / 100 if at not in (None, "") else None

    r = calculer_dict(s, c, var, annee, mois, bar, at)
    fin_cdd = c["type"] == "CDD" and c.get("date_fin") and d0 <= c["date_fin"] <= d1
    if fin_cdd and var.get("indemnite_fin_contrat") in (None, "") and var.get("fin_cdd", True) is not False:
        base = _cumul_brut_contrat(st, c["id"], (annee, mois)) + r["brut"]
        var["indemnite_fin_contrat"] = round(base * bar["indemnite_fin_cdd"])
        r = calculer_dict(s, c, var, annee, mois, bar, at)
    if c.get("mode") == "journalier" and not var.get("jours"):
        r["alertes"].append("Nombre de jours travaillés à saisir.")
    if c.get("mode") == "horaire" and not var.get("heures"):
        r["alertes"].append("Nombre d'heures travaillées à saisir.")
    r["variables_effectives"] = var
    instantane = {"salarie": s, "contrat": c, "entreprise": ent, "periode": {"annee": annee, "mois": mois}}
    return r, instantane


def cumuls(st: Stockage, salarie_id: int, annee: int, mois: int, courant: dict | None = None) -> dict:
    """Cumuls de l'année civile : bulletins clôturés des mois précédents + bulletin courant."""
    keys = ("brut", "brut_imposable", "cnps_salarie", "its", "net_a_payer", "charges_patronales")
    tot = dict.fromkeys(keys, 0)
    for r in st.q("SELECT b.resultat FROM bulletins b JOIN periodes p ON p.id=b.periode_id WHERE b.salarie_id=? "
                  "AND p.annee=? AND p.mois<? AND p.statut='cloturee'", (salarie_id, annee, mois)):
        if r["resultat"]:
            res = json.loads(r["resultat"])
            for k in keys:
                tot[k] += res.get(k, 0)
    if courant:
        for k in keys:
            tot[k] += courant.get(k, 0)
    return tot


def bulletin_complet(st: Stockage, bid: int) -> dict:
    b = st.bulletin(bid)
    p = st.periode(b["periode_id"])
    if p["statut"] == "cloturee" and b["resultat"]:
        r, inst = b["resultat"], b["instantane"]
    else:
        r, inst = calculer_bulletin(st, b, p)
    b["resultat"], b["instantane"] = r, inst
    b["cumuls"] = cumuls(st, b["salarie_id"], p["annee"], p["mois"], r)
    b["periode"] = p
    return b


def periode_complete(st: Stockage, pid: int) -> dict:
    synchroniser(st, pid)
    p = st.periode(pid)
    bar = bareme(st)
    lignes = []
    for b in st.bulletins(pid):
        if p["statut"] == "cloturee" and b["resultat"]:
            r, inst = b["resultat"], b["instantane"]
        else:
            r, inst = calculer_bulletin(st, b, p, bar)
        s, c = inst["salarie"], inst["contrat"]
        lignes.append({"id": b["id"], "salarie_id": b["salarie_id"], "contrat_id": b["contrat_id"],
                       "matricule": s["matricule"], "nom": f"{s['nom']} {s.get('prenoms', '')}".strip(),
                       "poste": c.get("poste", ""), "type": c["type"], "mode": c.get("mode", "mensuel"),
                       "variables": b["variables"], "resultat": r})
    lignes.sort(key=lambda x: x["nom"])
    keys = ("brut", "brut_imposable", "cnps_salarie", "cmu_salarie", "its", "total_retenues", "net_a_payer",
            "charges_patronales", "cout_employeur")
    totaux = {k: sum(l["resultat"][k] for l in lignes) for k in keys}
    p["libelle"] = libelle_periode(p["annee"], p["mois"])
    return {"periode": p, "bulletins": lignes, "totaux": totaux}


def cloturer(st: Stockage, pid: int) -> None:
    synchroniser(st, pid)
    p = st.periode(pid)
    if p["statut"] == "cloturee":
        raise ValueError("La période est déjà clôturée.")
    bar = bareme(st)
    for b in st.bulletins(pid):
        r, inst = calculer_bulletin(st, b, p, bar)
        st.figer_bulletin(b["id"], r, inst)
    st.statut_periode(pid, "cloturee")


def rouvrir(st: Stockage, pid: int) -> None:
    p = st.periode(pid)
    plus_recent = st.q("SELECT 1 FROM periodes WHERE statut='cloturee' AND (annee>? OR (annee=? AND mois>?))",
                       (p["annee"], p["annee"], p["mois"]), un=True)
    if plus_recent:
        raise ValueError("Une période plus récente est clôturée : rouvrez-la d'abord (les cumuls en dépendent).")
    for b in st.bulletins(pid):
        st.figer_bulletin(b["id"], None, None)
    st.statut_periode(pid, "ouverte")


# ---------------------------------------------------------------------------- alertes
def alertes(st: Stockage, aujourd_hui: date | None = None) -> list[dict]:
    jour = aujourd_hui or date.today()
    bar = bareme(st)
    out = []
    salaries = {s["id"]: s for s in st.salaries()}
    for c in st.contrats():
        s = salaries.get(c["salarie_id"])
        if not s or not s["actif"] or c.get("statut") == "termine":
            continue
        nom = f"{s['nom']} {s.get('prenoms', '')}".strip()
        base = {"salarie_id": s["id"], "contrat_id": c["id"], "nom": nom}
        debut = date.fromisoformat(c["date_debut"])
        if c.get("date_fin"):
            fin = date.fromisoformat(c["date_fin"])
            reste = (fin - jour).days
            if reste < 0:
                out.append({**base, "niveau": "urgent", "texte": f"{c['type']} échu depuis le {fin:%d/%m/%Y} : "
                            "terminer le contrat, le renouveler par avenant ou conclure un CDI."})
            elif reste <= 30:
                out.append({**base, "niveau": "attention", "texte": f"{c['type']} se termine le {fin:%d/%m/%Y} "
                            f"(dans {reste} jour{'s' if reste > 1 else ''})."})
            if c["type"] == "CDD" and (fin - debut).days > 731:
                out.append({**base, "niveau": "urgent", "texte": "CDD de plus de deux ans, renouvellements compris : "
                            "au-delà, le contrat devient un CDI (Code du travail)."})
        essai = c.get("essai_mois")
        if essai:
            m = debut.month - 1 + int(float(essai))
            j = min(debut.day, calendar.monthrange(debut.year + m // 12, m % 12 + 1)[1])
            fin_essai = date(debut.year + m // 12, m % 12 + 1, j) - timedelta(days=1)
            if 0 <= (fin_essai - jour).days <= 15:
                out.append({**base, "niveau": "info", "texte": f"Fin de la période d'essai le {fin_essai:%d/%m/%Y}."})
        cc = st.contrat_au(c["id"], jour.isoformat())
        if cc.get("mode", "mensuel") == "mensuel" \
                and float(cc.get("salaire_base") or 0) < bar["smig_mensuel"]:
            out.append({**base, "niveau": "urgent", "texte": "Salaire de base inférieur au SMIG."})
    for s in salaries.values():
        if s["actif"] and not s.get("numero_cnps"):
            out.append({"salarie_id": s["id"], "nom": f"{s['nom']} {s.get('prenoms', '')}".strip(),
                        "niveau": "info", "texte": "Numéro CNPS non renseigné."})
    ordre = {"urgent": 0, "attention": 1, "info": 2}
    return sorted(out, key=lambda a: ordre[a["niveau"]])
