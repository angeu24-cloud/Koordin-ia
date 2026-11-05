"""Escaliers en béton armé : géométrie (Blondel), paillasse + palier, ferraillage.

Modèle : volée (paillasse inclinée) prolongée par son palier, travée unique appuyée
sur les poutres palières (ou murs), semi-encastrée : Mt = 0,85·M0, Ma = 0,30·M0.
Une ou deux volées selon la largeur de la cage (deux volées si largeur ≥ 2 m).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .codes.common import bar_area

RISER_TARGET = 0.17       # hauteur de marche visée (m)
BLONDEL = 0.63            # 2h + g
G_STEPS_DENSITY = 22.0    # béton des marches (kN/m³)
G_FINISH = 1.3            # revêtement + enduit sous face (kN/m²)
Q_STAIR = 2.5             # kN/m²


@dataclass
class StairResult:
    floor: str            # « RDC → Étage 1 »
    name: str
    height: float         # hauteur à franchir (m)
    risers: int
    riser_h: float        # m
    going: float          # giron (m)
    flights: int
    width: float          # emmarchement (m)
    cage: tuple[float, float]   # dimensions de la cage (long, court) en m
    span: float           # portée paillasse + palier (m)
    flight_len: float     # projection horizontale de la volée (m)
    landing: float        # profondeur du palier (m)
    thickness: float      # épaisseur de paillasse (m)
    angle: float          # degrés
    g_flight: float       # kN/m² projeté
    g_landing: float
    g_mean: float         # permanent moyen projeté (kN/m²), à comparer au forfait de la descente
    m0: float             # kN.m/m
    as_bottom: float      # cm²/m
    bars_bottom: str
    as_top: float
    bars_top: str
    bars_dist: str
    landing_beam_load: float   # charge linéique ELU transmise à chaque poutre palière (kN/m)
    notes: list[str] = field(default_factory=list)


def _bars_per_meter(as_cm2: float) -> str:
    for d in (8, 10, 12, 14, 16, 20):
        e = bar_area(d) / as_cm2 if as_cm2 > 0 else 1.0
        e = min(0.25, math.floor(e * 100) / 100)
        if e >= 0.10:
            return f"HA{d} e={e * 100:.0f} cm"
    return "à revoir (section insuffisante)"


def design_stair(code, floor: str, name: str, cage_x: float, cage_y: float, height: float) -> StairResult:
    notes: list[str] = []
    long_, short = max(cage_x, cage_y), min(cage_x, cage_y)
    n = max(2, math.ceil(height / RISER_TARGET - 1e-9))
    h = height / n
    going = min(max(BLONDEL - 2 * h, 0.25), 0.32)
    flights = 2 if short >= 2.0 else 1
    width = short / flights
    per_flight = math.ceil(n / flights)
    flight_len = (per_flight - 1) * going
    landing = long_ - flight_len
    if landing < 0.9:
        notes.append(f"Cage trop courte : {per_flight} marches × {going * 100:.0f} cm = {flight_len:.2f} m "
                     f"pour {long_:.2f} m disponibles (palier < 0,90 m)")
        landing = max(landing, 0.0)
    if width < 0.9:
        notes.append(f"Emmarchement {width:.2f} m < 0,90 m")
    if not 0.60 <= 2 * h + going <= 0.66:
        notes.append("Loi de Blondel hors de [60 ; 66] cm")
    span = flight_len + landing if flights == 1 else long_
    e = max(0.12, math.ceil(span / 30 * 100) / 100)
    alpha = math.atan(h / going)
    g_flight = 25 * e / math.cos(alpha) + G_STEPS_DENSITY * h / 2 + G_FINISH
    g_land = 25 * e + G_FINISH
    lp = min(flight_len, span)
    lpal = max(0.0, span - lp)
    g_mean = (g_flight * lp + g_land * lpal) / span if span else g_flight
    # moment maximal d'une travée isostatique à deux charges réparties (volée puis palier)
    pu_f = code.elu(g_flight, Q_STAIR)
    pu_l = code.elu(g_land, Q_STAIR)
    xs = np.linspace(0, span, 201)
    w = np.where(xs <= lp, pu_f, pu_l)
    dx = span / 200
    total = float(np.trapezoid(w, xs)) if hasattr(np, "trapezoid") else float(np.trapz(w, xs))
    moment_about_0 = float(np.sum(w * xs) * dx)
    rb = moment_about_0 / span
    ra = total - rb
    shear = ra - np.concatenate([[0], np.cumsum((w[1:] + w[:-1]) / 2 * dx)])
    mom = np.concatenate([[0], np.cumsum((shear[1:] + shear[:-1]) / 2 * dx)])
    m0 = float(mom.max())
    as_b, _, n1 = code.flexure(0.85 * m0, 1.0, e)
    as_t, _, n2 = code.flexure(0.30 * m0, 1.0, e)
    notes += n1 + n2
    as_dist = max(as_b / 4, 1.2)
    # cisaillement sans armatures d'effort tranchant : τu ≤ 0,05·fc (dalles)
    fc = getattr(code, "fc28", getattr(code, "fck", 25.0))
    tau = max(ra, rb) / 1000 / (1.0 * 0.9 * e)
    if tau > 0.05 * fc:
        notes.append(f"τu = {tau:.2f} MPa > 0,05·fc : augmenter l'épaisseur de paillasse")
    return StairResult(
        floor, name, round(height, 2), n, round(h, 3), round(going, 3), flights, round(width, 2),
        (round(long_, 2), round(short, 2)), round(span, 2), round(flight_len, 2), round(landing, 2), e,
        round(math.degrees(alpha), 1), round(g_flight, 2), round(g_land, 2), round(g_mean, 2), round(m0, 1),
        round(as_b, 2), _bars_per_meter(as_b), round(as_t, 2), _bars_per_meter(as_t), _bars_per_meter(as_dist),
        round(max(ra, rb), 1), notes,
    )
