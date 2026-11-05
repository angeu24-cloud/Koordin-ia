"""Descente de charges : planchers → poutres → poteaux → fondations.

Méthode « bâtiment courant » :
- report des charges de plancher sur les poutres (porteur dans un sens pour les
  planchers à corps creux ; lignes de rupture à 45° pour les dalles pleines),
- réactions isostatiques des poutres sur les poteaux, majorées de 15 % (2 travées)
  ou 10 % (≥ 3 travées) sur les appuis voisins de rive (BAEL B.8.1,1),
- cumul niveau par niveau avec la loi de dégression des charges d'exploitation
  (NF P06-001).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .model import Beam, Building, LoadSettings

CONCRETE = 25.0  # kN/m³


@dataclass
class BeamLoad:
    """Charges linéiques d'une poutre pour un niveau (kN/m) et charges totales (kN)."""
    g_m: float = 0.0   # équivalent uniforme pour le moment
    q_m: float = 0.0
    g_v: float = 0.0   # équivalent uniforme pour l'effort tranchant
    q_v: float = 0.0
    g_tot: float = 0.0
    q_tot: float = 0.0

    def add(self, other: "BeamLoad") -> None:
        for k in ("g_m", "q_m", "g_v", "q_v", "g_tot", "q_tot"):
            setattr(self, k, getattr(self, k) + getattr(other, k))


@dataclass
class ColumnStorey:
    storey: int          # 1 = rez-de-chaussée (le plus chargé)
    g: float             # kN cumulés en pied de poteau
    q: float             # kN cumulés après dégression
    q_raw: float         # kN cumulés sans dégression


@dataclass
class BeamLine:
    beams: list[str]            # poutres consécutives
    supports: list[str]         # poteaux (len = len(beams) + 1)


@dataclass
class TakedownResult:
    floor_loads: dict[str, BeamLoad] = field(default_factory=dict)   # étage courant
    roof_loads: dict[str, BeamLoad] = field(default_factory=dict)    # terrasse
    columns: dict[str, list[ColumnStorey]] = field(default_factory=dict)
    lines: list[BeamLine] = field(default_factory=list)
    surface_g_floor: float = 0.0
    surface_q_floor: float = 0.0
    surface_g_roof: float = 0.0
    surface_q_roof: float = 0.0
    warnings: list[str] = field(default_factory=list)


def degression_coef(m: int) -> float:
    """Coefficient appliqué à Q1+…+Qm (m étages sous la terrasse), NF P06-001."""
    table = {0: 1.0, 1: 1.0, 2: 0.95, 3: 0.90, 4: 0.85}
    return table.get(m, (3 + m) / (2 * m))


def _panel_to_beams(bld: Building, p, g: float, q: float, floor_type: str) -> dict[str, BeamLoad]:
    """Charges transmises par un panneau à ses 4 poutres [bas, haut, gauche, droite]."""
    out: dict[str, BeamLoad] = {}
    bottom, top, left, right = p.beams
    lx, ly = p.lx, p.ly           # lx selon X (portée des poutres bas/haut), ly selon Y
    short, long_ = min(lx, ly), max(lx, ly)
    rho = short / long_
    long_beams = (bottom, top) if lx >= ly else (left, right)     # poutres parallèles au grand côté
    short_beams = (left, right) if lx >= ly else (bottom, top)

    def put(bid: str, w_m: float, w_v: float, tot: float) -> None:
        bl = out.setdefault(bid, BeamLoad())
        bl.g_m += g * w_m
        bl.q_m += q * w_m
        bl.g_v += g * w_v
        bl.q_v += q * w_v
        bl.g_tot += g * tot
        bl.q_tot += q * tot

    if floor_type == "corps_creux" or rho < 0.4:
        # Porteur dans un sens : les poutrelles portent sur le petit côté
        w = short / 2
        for bid in long_beams:
            put(bid, w, w, w * long_)
    else:
        # Dalle portant dans deux sens : trapèzes sur les grands côtés, triangles sur les petits
        for bid in long_beams:
            put(bid, short / 2 * (1 - rho ** 2 / 3), short / 2 * (1 - rho / 2), short / 4 * (2 * long_ - short))
        for bid in short_beams:
            put(bid, short / 3, short / 4, short ** 2 / 4)
    return out


def beam_lines(bld: Building) -> list[BeamLine]:
    """Regroupe les poutres en files continues (même direction, appuis communs)."""
    by_start: dict[tuple[str, str], Beam] = {}
    ends: set[tuple[str, str]] = set()
    for b in bld.beams:
        by_start[(b.direction, b.start)] = b
        ends.add((b.direction, b.end))
    lines: list[BeamLine] = []
    for b in bld.beams:
        if (b.direction, b.start) in ends:
            continue  # pas un début de file
        seq, sup = [b.id], [b.start, b.end]
        cur = b
        while (cur.direction, cur.end) in by_start:
            cur = by_start[(cur.direction, cur.end)]
            seq.append(cur.id)
            sup.append(cur.end)
        lines.append(BeamLine(seq, sup))
    return lines


def compute_takedown(bld: Building, ls: LoadSettings) -> TakedownResult:
    res = TakedownResult()
    cols = bld.column_map()
    beams = bld.beam_map()
    res.lines = beam_lines(bld)

    res.surface_g_floor = ls.g_floor + ls.g_finishes
    res.surface_q_floor = ls.q_floor
    res.surface_g_roof = ls.g_floor + ls.g_roof_extra
    res.surface_q_roof = ls.q_roof

    # Poutres de rive : bordées par un seul panneau
    panels_per_beam: dict[str, int] = defaultdict(int)
    for p in bld.panels:
        for bid in p.beams:
            panels_per_beam[bid] += 1

    def level_loads(g: float, q: float, roof: bool) -> dict[str, BeamLoad]:
        loads = {b.id: BeamLoad() for b in bld.beams}
        for p in bld.panels:
            for bid, bl in _panel_to_beams(bld, p, g, q, ls.floor_type).items():
                loads[bid].add(bl)
        for b in bld.beams:
            L = b.length(cols)
            pp = CONCRETE * b.b * b.h
            if not roof and ls.facade_load and panels_per_beam[b.id] <= 1:
                pp += ls.facade_load
            loads[b.id].add(BeamLoad(g_m=pp, g_v=pp, g_tot=pp * L))
        return loads

    res.floor_loads = level_loads(res.surface_g_floor, res.surface_q_floor, roof=False)
    res.roof_loads = level_loads(res.surface_g_roof, res.surface_q_roof, roof=True)

    # Coefficients de continuité sur les appuis
    coef: dict[tuple[str, str], float] = {}  # (poutre, poteau) -> majoration
    if ls.continuity:
        for line in res.lines:
            n = len(line.beams)
            targets: dict[int, float] = {}
            if n == 2:
                targets = {1: 1.15}
            elif n >= 3:
                targets = {1: 1.10, n - 1: 1.10}
            for idx, f in targets.items():
                sup = line.supports[idx]
                for bid in (line.beams[idx - 1], line.beams[idx]):
                    coef[(bid, sup)] = f

    def reactions(loads: dict[str, BeamLoad]) -> dict[str, tuple[float, float]]:
        r: dict[str, list[float]] = {c.id: [0.0, 0.0] for c in bld.columns}
        for b in bld.beams:
            bl = loads[b.id]
            for cid in (b.start, b.end):
                f = coef.get((b.id, cid), 1.0)
                r[cid][0] += f * bl.g_tot / 2
                r[cid][1] += f * bl.q_tot / 2
        return {k: (v[0], v[1]) for k, v in r.items()}

    r_floor = reactions(res.floor_loads)
    r_roof = reactions(res.roof_loads)

    n = bld.n_levels
    for c in bld.columns:
        pp_col = CONCRETE * c.b * c.h * bld.floor_height
        storeys: list[ColumnStorey] = []
        g_cum = 0.0
        q_list: list[float] = []  # Q0 (terrasse), Q1, Q2…
        for level in range(n, 0, -1):  # du haut vers le bas
            g_lvl, q_lvl = r_roof[c.id] if level == n else r_floor[c.id]
            g_cum += g_lvl + pp_col
            q_list.append(q_lvl)
            m = len(q_list) - 1
            q_raw = sum(q_list)
            if ls.degression and m >= 2:
                q_cum = q_list[0] + degression_coef(m) * sum(q_list[1:])
            else:
                q_cum = q_raw
            storeys.append(ColumnStorey(storey=level, g=g_cum, q=q_cum, q_raw=q_raw))
        res.columns[c.id] = storeys

    # Contrôle des conditions de la méthode forfaitaire
    for line in res.lines:
        spans = [beams[b].length(cols) for b in line.beams]
        for a, b in zip(spans, spans[1:]):
            if not 0.8 <= a / b <= 1.25:
                res.warnings.append(
                    f"File {'-'.join(line.supports)} : rapport de portées {a:.2f}/{b:.2f} hors [0,8 ; 1,25] — "
                    "moments forfaitaires à confirmer par un calcul de continuité (Caquot)."
                )
                break
    if ls.q_floor > max(2 * res.surface_g_floor, 5.0):
        res.warnings.append("Q > max(2G ; 5 kN/m²) : la méthode forfaitaire n'est pas applicable.")
    return res
