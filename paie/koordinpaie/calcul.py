"""Moteur de calcul de la paie (Côte d'Ivoire).

Fonctions pures : aucune base de données ici. Toutes les sommes sont en FCFA entiers.

Ordre du calcul d'un bulletin :
  salaire de base (mensuel, journalier ou horaire, au prorata en cas d'entrée ou de sortie)
  + sursalaire, prime d'ancienneté, heures supplémentaires, primes, avantages
  − absences non payées
  = salaire brut ; brut imposable = brut − éléments non imposables (transport dans la limite)
  − CNPS retraite (plafonnée), CMU, ITS (barème progressif − réduction pour charges de famille)
  − acomptes et autres retenues
  = net à payer
Charges patronales : CNPS (retraite, prestations familiales, maternité, accident du travail),
CMU, impôt patronal sur salaires, FDFP (taxe d'apprentissage, formation continue).
"""
from __future__ import annotations

import calendar
import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BAREME_DEFAUT = Path(__file__).with_name("bareme_ci.json")


def charger_bareme(surcharges: dict | None = None) -> dict:
    """Barème livré, fusionné avec les modifications enregistrées par l'utilisateur."""
    bareme = json.loads(BAREME_DEFAUT.read_text(encoding="utf-8"))
    if surcharges:
        fusionner(bareme, surcharges)
    return bareme


def fusionner(base: dict, ajout: dict) -> dict:
    for k, v in ajout.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            fusionner(base[k], v)
        else:
            base[k] = v
    return base


def arrondi(x: float) -> int:
    """Arrondi au franc le plus proche (0,5 vers le haut)."""
    return int(math.floor(x + 0.5))


# ---------------------------------------------------------------------------- données d'entrée
@dataclass
class Salarie:
    date_embauche: date
    marie: bool = False
    enfants: int = 0
    parts: float | None = None          # nombre de parts imposé (sinon calculé)
    expatrie: bool = False
    personnes_cmu: int = 0              # personnes à charge affiliées à la CMU (hors salarié)


@dataclass
class Element:
    libelle: str
    montant: float
    imposable: bool = True
    cotisable: bool = True              # soumis à la CNPS (suit « imposable » par défaut)


@dataclass
class Contrat:
    type: str = "CDI"                    # CDI, CDD, JOURNALIER
    mode: str = "mensuel"                # mensuel, journalier, horaire
    salaire_base: float = 0              # mensuel, ou taux journalier / horaire
    sursalaire: float = 0
    primes_fixes: list[Element] = field(default_factory=list)
    transport: float = 0
    heures_mensuelles: float | None = None


@dataclass
class Variables:
    jours: float = 0                    # jours travaillés (journalier)
    heures: float = 0                   # heures travaillées (horaire)
    prorata: float = 1.0                # fraction du mois sous contrat (mensuel)
    hs15: float = 0
    hs50: float = 0
    hs75: float = 0
    hs100: float = 0
    heures_absence: float = 0
    primes: list[Element] = field(default_factory=list)
    acompte: float = 0
    autres_retenues: list[Element] = field(default_factory=list)
    indemnite_fin_contrat: float = 0    # montant déjà calculé (3 % du brut du CDD)


@dataclass
class Ligne:
    code: str
    libelle: str
    base: float | None = None
    taux: float | None = None
    gain: int = 0
    retenue: int = 0
    patronal: int = 0
    taux_patronal: float | None = None


# ---------------------------------------------------------------------------- règles
def anciennete_annees(embauche: date, au: date) -> int:
    ans = au.year - embauche.year - ((au.month, au.day) < (embauche.month, embauche.day))
    return max(ans, 0)


def taux_anciennete(annees: int, bareme: dict) -> float:
    a = bareme["anciennete"]
    if annees < a["debut_annees"]:
        return 0.0
    return min(annees * a["taux_par_an"], a["taux_max"])


def nombre_parts(s: Salarie, bareme: dict) -> float:
    """1 part (célibataire) ou 2 (marié), + 0,5 par enfant à charge, plafonné."""
    if s.parts:
        p = s.parts
    else:
        p = (2.0 if s.marie else 1.0) + 0.5 * max(s.enfants, 0)
        if not s.marie and s.enfants > 0:
            p += 0.5                     # parent isolé
    return min(p, bareme["its"]["parts_max"])


def impot_bareme(assiette: float, tranches: list) -> float:
    impot, bas = 0.0, 0.0
    for haut, taux in tranches:
        if haut is None or assiette <= haut:
            impot += (assiette - bas) * taux
            break
        impot += (haut - bas) * taux
        bas = haut
    return max(impot, 0.0)


def its(assiette: float, parts: float, bareme: dict) -> tuple[int, int, int]:
    """(impôt brut, réduction pour charges de famille, ITS dû)."""
    brut = arrondi(impot_bareme(assiette, bareme["its"]["tranches"]))
    reduc = arrondi(max(parts - 1, 0) / 0.5 * bareme["its"]["reduction_par_demi_part"])
    return brut, min(reduc, brut), max(brut - reduc, 0)


def prorata_mois(annee: int, mois: int, debut: date | None, fin: date | None) -> float:
    """Fraction du mois couverte par le contrat (jours calendaires)."""
    nb = calendar.monthrange(annee, mois)[1]
    d0, d1 = date(annee, mois, 1), date(annee, mois, nb)
    a = max(d0, debut) if debut else d0
    b = min(d1, fin) if fin else d1
    if b < a:
        return 0.0
    return round(((b - a).days + 1) / nb, 4)


# ---------------------------------------------------------------------------- bulletin
def calculer(salarie: Salarie, contrat: Contrat, var: Variables, annee: int, mois: int,
             bareme: dict | None = None, accident_travail: float | None = None) -> dict:
    b = bareme or charger_bareme()
    cn = b["cnps"]
    fin_mois = date(annee, mois, calendar.monthrange(annee, mois)[1])
    lignes: list[Ligne] = []
    h_mens = contrat.heures_mensuelles or b["heures_mensuelles"]

    # --- salaire de base
    if contrat.mode == "journalier":
        base = contrat.salaire_base * var.jours
        lignes.append(Ligne("BASE", "Salaire de base (journalier)", var.jours, contrat.salaire_base,
                            gain=arrondi(base)))
        taux_h = contrat.salaire_base / 8
    elif contrat.mode == "horaire":
        base = contrat.salaire_base * var.heures
        lignes.append(Ligne("BASE", "Salaire de base (horaire)", var.heures, contrat.salaire_base,
                            gain=arrondi(base)))
        taux_h = contrat.salaire_base
    else:
        base = contrat.salaire_base * var.prorata
        lib = "Salaire de base" + (f" (prorata {var.prorata:.2%})" if var.prorata < 1 else "")
        lignes.append(Ligne("BASE", lib, contrat.salaire_base, var.prorata if var.prorata < 1 else None,
                            gain=arrondi(base)))
        taux_h = (contrat.salaire_base + contrat.sursalaire) / h_mens

    # --- ancienneté (sur le salaire de base)
    ans = anciennete_annees(salarie.date_embauche, fin_mois)
    t_anc = taux_anciennete(ans, b)
    if t_anc:
        lignes.append(Ligne("ANC", f"Prime d'ancienneté ({ans} ans)", arrondi(base), t_anc,
                            gain=arrondi(base * t_anc)))

    if contrat.sursalaire:
        f = var.prorata if contrat.mode == "mensuel" else 1
        lignes.append(Ligne("SURSAL", "Sursalaire", None, None, gain=arrondi(contrat.sursalaire * f)))

    # --- heures supplémentaires
    for code, lib in (("hs15", "Heures sup. 41e à 46e h (+15 %)"), ("hs50", "Heures sup. au-delà de 46 h (+50 %)"),
                      ("hs75", "Heures sup. nuit / dimanche / férié (+75 %)"),
                      ("hs100", "Heures sup. nuit dimanche / férié (+100 %)")):
        h = getattr(var, code)
        if h:
            maj = b["heures_sup"][code]
            lignes.append(Ligne(code.upper(), lib, h, round(taux_h * (1 + maj), 2),
                                gain=arrondi(h * taux_h * (1 + maj))))

    # --- absences
    if var.heures_absence and contrat.mode == "mensuel":
        lignes.append(Ligne("ABS", "Absences non rémunérées", var.heures_absence, round(taux_h, 2),
                            gain=-arrondi(var.heures_absence * taux_h)))

    # --- primes et indemnités
    non_imposable = 0
    non_cotisable = 0
    for i, p in enumerate(list(contrat.primes_fixes) + list(var.primes)):
        m = arrondi(p.montant)
        if not m:
            continue
        lignes.append(Ligne(f"PRIME{i}", p.libelle + ("" if p.imposable else " (non imposable)"), gain=m))
        if not p.imposable:
            non_imposable += m
        if not (p.imposable and p.cotisable):
            non_cotisable += m

    if var.indemnite_fin_contrat:
        lignes.append(Ligne("FINCDD", "Indemnité de fin de contrat", None, b["indemnite_fin_cdd"],
                            gain=arrondi(var.indemnite_fin_contrat)))

    if contrat.transport:
        tr = arrondi(contrat.transport * (var.prorata if contrat.mode == "mensuel" else 1))
        exo = min(tr, b["transport_non_imposable"])
        lignes.append(Ligne("TRANSP", "Indemnité de transport", None, None, gain=tr))
        non_imposable += exo
        non_cotisable += exo

    brut = sum(l.gain for l in lignes)
    brut_imposable = max(brut - non_imposable, 0)
    assiette_cnps = max(brut - non_cotisable, 0)

    # --- cotisations sociales
    retenues: list[Ligne] = []
    base_ret = min(assiette_cnps, cn["plafond_retraite"])
    retenues.append(Ligne("CNPS_RET", "CNPS — retraite", base_ret, cn["retraite_salarie"],
                          retenue=arrondi(base_ret * cn["retraite_salarie"]),
                          patronal=arrondi(base_ret * cn["retraite_employeur"]),
                          taux_patronal=cn["retraite_employeur"]))
    base_aut = min(assiette_cnps, cn["plafond_autres_branches"])
    t_at = cn["accident_travail"] if accident_travail is None else accident_travail
    for code, lib, t in (("CNPS_PF", "CNPS — prestations familiales", cn["prestations_familiales"]),
                         ("CNPS_MAT", "CNPS — assurance maternité", cn["maternite"]),
                         ("CNPS_AT", "CNPS — accident du travail", t_at)):
        retenues.append(Ligne(code, lib, base_aut, None, patronal=arrondi(base_aut * t), taux_patronal=t))

    cmu = b["cmu"]
    retenues.append(Ligne("CMU", "Couverture maladie universelle (CMU)", 1 + salarie.personnes_cmu, None,
                          retenue=arrondi(cmu["salarie"] + salarie.personnes_cmu * cmu["par_personne_a_charge"]),
                          patronal=arrondi(cmu["employeur"])))

    # --- impôt sur salaire
    parts = nombre_parts(salarie, b)
    its_brut, reduc, its_du = its(brut_imposable, parts, b)
    retenues.append(Ligne("ITS", f"ITS (barème) — {parts:g} part(s)", brut_imposable, None, retenue=its_brut))
    if reduc:
        retenues.append(Ligne("RICF", "Réduction pour charges de famille", None, None, retenue=-reduc))

    emp = b["employeur"]
    t_ip = emp["impot_patronal_expatrie"] if salarie.expatrie else emp["impot_patronal_local"]
    retenues.append(Ligne("IS_PAT", "Impôt sur salaires — part patronale", brut_imposable, None,
                          patronal=arrondi(brut_imposable * t_ip), taux_patronal=t_ip))
    retenues.append(Ligne("FDFP_TA", "FDFP — taxe d'apprentissage", brut_imposable, None,
                          patronal=arrondi(brut_imposable * emp["taxe_apprentissage"]),
                          taux_patronal=emp["taxe_apprentissage"]))
    retenues.append(Ligne("FDFP_FPC", "FDFP — formation professionnelle continue", brut_imposable, None,
                          patronal=arrondi(brut_imposable * emp["formation_continue"]),
                          taux_patronal=emp["formation_continue"]))

    # --- retenues diverses (après net imposable)
    divers: list[Ligne] = []
    if var.acompte:
        divers.append(Ligne("ACOMPTE", "Acompte / avance sur salaire", retenue=arrondi(var.acompte)))
    for i, r in enumerate(var.autres_retenues):
        if r.montant:
            divers.append(Ligne(f"RET{i}", r.libelle, retenue=arrondi(r.montant)))

    total_cotis = sum(l.retenue for l in retenues)
    total_divers = sum(l.retenue for l in divers)
    total_patronal = sum(l.patronal for l in retenues)
    net = brut - total_cotis - total_divers

    def d(l: Ligne) -> dict:
        return {k: v for k, v in l.__dict__.items() if v not in (None, 0) or k in ("code", "libelle")}

    return {
        "periode": f"{annee:04d}-{mois:02d}",
        "anciennete_annees": ans,
        "parts": parts,
        "taux_horaire": round(taux_h, 2),
        "gains": [d(l) for l in lignes],
        "cotisations": [d(l) for l in retenues],
        "retenues": [d(l) for l in divers],
        "brut": brut,
        "brut_imposable": brut_imposable,
        "assiette_cnps": assiette_cnps,
        "cnps_salarie": sum(l.retenue for l in retenues if l.code.startswith("CNPS")),
        "cmu_salarie": next(l.retenue for l in retenues if l.code == "CMU"),
        "its": its_du,
        "total_cotisations": total_cotis,
        "total_retenues": total_divers,
        "net_a_payer": net,
        "charges_patronales": total_patronal,
        "cout_employeur": brut + total_patronal,
        "detail_patronal": {l.code: l.patronal for l in retenues if l.patronal},
        "alertes": _alertes(contrat, var, base, b),
    }


def _alertes(contrat: Contrat, var: Variables, base: float, b: dict) -> list[str]:
    out = []
    if contrat.mode == "mensuel" and contrat.salaire_base < b["smig_mensuel"]:
        out.append(f"Salaire de base inférieur au SMIG ({b['smig_mensuel']:,} FCFA).".replace(",", " "))
    hs = var.hs15 + var.hs50 + var.hs75 + var.hs100
    if hs > 75:
        out.append("Plus de 75 heures supplémentaires dans le mois : vérifier le contingent autorisé.")
    return out


# ---------------------------------------------------------------------------- conversions
def _date(v) -> date | None:
    if not v:
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _elements(lst) -> list[Element]:
    out = []
    for p in lst or []:
        imp = bool(p.get("imposable", True))
        out.append(Element(str(p.get("libelle", "Prime")), float(p.get("montant") or 0), imp,
                           bool(p.get("cotisable", imp))))
    return out


def salarie_de(d: dict) -> Salarie:
    return Salarie(date_embauche=_date(d.get("date_embauche")) or date.today(), marie=bool(d.get("marie")),
                   enfants=int(d.get("enfants") or 0), parts=float(d["parts"]) if d.get("parts") else None,
                   expatrie=bool(d.get("expatrie")), personnes_cmu=int(d.get("personnes_cmu") or 0))


def contrat_de(d: dict) -> Contrat:
    return Contrat(type=d.get("type", "CDI"), mode=d.get("mode", "mensuel"),
                   salaire_base=float(d.get("salaire_base") or 0), sursalaire=float(d.get("sursalaire") or 0),
                   primes_fixes=_elements(d.get("primes_fixes")), transport=float(d.get("transport") or 0),
                   heures_mensuelles=float(d["heures_mensuelles"]) if d.get("heures_mensuelles") else None)


VARIABLES_NUM = ("jours", "heures", "prorata", "hs15", "hs50", "hs75", "hs100", "heures_absence", "acompte",
                 "indemnite_fin_contrat")


def variables_de(d: dict) -> Variables:
    v = Variables()
    for k in VARIABLES_NUM:
        if d.get(k) not in (None, ""):
            setattr(v, k, float(d[k]))
    v.primes = _elements(d.get("primes"))
    v.autres_retenues = _elements(d.get("autres_retenues"))
    return v


def calculer_dict(salarie: dict, contrat: dict, variables: dict, annee: int, mois: int,
                  bareme: dict | None = None, accident_travail: float | None = None) -> dict:
    return calculer(salarie_de(salarie), contrat_de(contrat), variables_de(deepcopy(variables)), annee, mois,
                    bareme, accident_travail)
