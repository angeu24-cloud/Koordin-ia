"""Réseau d'évacuation gravitaire des eaux usées et vannes (branchements, collecteurs, regards).

- Débit : NF EN 12056-2 (système I) : Qww = K √ΣDU, K = 0,5 en logement ; jamais inférieur au
  débit de l'appareil le plus fort (WC : 2 L/s).
- Capacité : Manning-Strickler en écoulement partiel (Ks = 90 pour le PVC vieilli), remplissage
  maximal h/d = 0,5 pour les collecteurs (ventilation, réserve), vitesse d'autocurage ≥ 0,6 m/s
  conseillée.
- Diamètre minimal : Ø110 PVC dès qu'un WC est raccordé (DTU 60.11).
- Regards : à chaque changement de direction, jonction et tête de réseau ; dimension selon la
  profondeur du fil d'eau.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DU = {"wc": 2.0, "lavabo": 0.5, "douche": 0.6, "evier": 0.8, "baignoire": 0.8, "lave_linge": 0.8,
      "urinoir": 0.5, "lave_vaisselle": 0.8}
BRANCHEMENT = {"wc": 110, "lavabo": 40, "douche": 50, "evier": 50, "baignoire": 50, "lave_linge": 50,
               "urinoir": 50, "lave_vaisselle": 50}
PVC_INT = {40: 36.4, 50: 46.4, 75: 71.2, 90: 85.6, 110: 103.6, 125: 118.6, 160: 152.0, 200: 190.2}
K_LOGEMENT = 0.5


def q_ww(appareils: list[str], k: float = K_LOGEMENT) -> float:
    """Débit de projet (L/s)."""
    if not appareils:
        return 0.0
    s = sum(DU[a] for a in appareils)
    return round(max(k * math.sqrt(s), max(DU[a] for a in appareils)), 3)


def _partial(d: float, y: float) -> tuple[float, float]:
    """Section mouillée et rayon hydraulique d'une conduite circulaire (d en m, y = h/d)."""
    th = 2 * math.acos(1 - 2 * y)
    a = d ** 2 / 8 * (th - math.sin(th))
    p = d * th / 2
    return a, a / p


def capacite(dn: int, pente: float, remplissage: float = 0.5, ks: float = 90.0) -> float:
    """Débit (L/s) d'un tuyau PVC de diamètre extérieur `dn` à la pente donnée (m/m)."""
    a, r = _partial(PVC_INT[dn] / 1000, remplissage)
    return ks * a * r ** (2 / 3) * math.sqrt(pente) * 1000


def remplissage(dn: int, pente: float, q_ls: float, ks: float = 90.0) -> tuple[float, float]:
    """(h/d, vitesse m/s) pour le débit q (L/s)."""
    if q_ls <= 0:
        return 0.0, 0.0
    lo, hi = 1e-4, 0.999
    for _ in range(60):
        mid = (lo + hi) / 2
        if capacite(dn, pente, mid, ks) < q_ls:
            lo = mid
        else:
            hi = mid
    a, _ = _partial(PVC_INT[dn] / 1000, hi)
    return round(hi, 3), round(q_ls / 1000 / a, 2)


@dataclass
class Troncon:
    nom: str
    amont: str
    aval: str
    longueur: float
    pente: float
    appareils: list[str] = field(default_factory=list)   # appareils desservis en amont (cumulés)
    dn: int = 0
    q: float = 0.0
    h_d: float = 0.0
    v: float = 0.0
    fe_amont: float = 0.0
    fe_aval: float = 0.0
    notes: list[str] = field(default_factory=list)


def dimensionner(t: Troncon, h_d_max: float = 0.5, dn_min: int = 110) -> Troncon:
    t.q = q_ww(t.appareils)
    need_wc = any(a == "wc" for a in t.appareils)
    for dn in sorted(PVC_INT):
        if dn < (110 if need_wc else 40) or dn < dn_min:
            continue
        if capacite(dn, t.pente, h_d_max) >= t.q:
            t.dn = dn
            break
    else:
        t.dn = max(PVC_INT)
    t.h_d, t.v = remplissage(t.dn, t.pente, t.q)
    if t.v < 0.6:
        t.notes.append("vitesse < 0,6 m/s au débit de pointe : chasse des WC assurant l'autocurage")
    return t


def profil(troncons: list[Troncon], fe_depart: float, chutes: dict[str, float] | None = None) -> dict[str, float]:
    """Fils d'eau (m, négatifs sous le terrain), de l'amont vers l'aval ; `chutes` : chute dans un regard."""
    fe: dict[str, float] = {troncons[0].amont: fe_depart}
    for t in troncons:
        start = fe.get(t.amont, fe_depart) - (chutes or {}).get(t.amont, 0.0)
        t.fe_amont = round(start, 3)
        t.fe_aval = round(start - t.longueur * t.pente, 3)
        fe[t.aval] = min(fe.get(t.aval, math.inf), t.fe_aval)
    return fe


def regard(profondeur: float) -> str:
    """Dimension intérieure usuelle d'un regard selon la profondeur du fil d'eau (m)."""
    if profondeur <= 0.60:
        return "40 × 40"
    if profondeur <= 0.90:
        return "50 × 50"
    if profondeur <= 1.20:
        return "60 × 60"
    return "80 × 80"
