"""Descente de charges : planchers → poutres → poteaux → fondations.

Méthode des surfaces d'influence sur grille fine (valable pour les trames
régulières comme irrégulières) :

- le contour du plancher est découpé en cellules (10 cm par défaut) ;
- plancher à corps creux : chaque cellule est portée par la poutre la plus proche
  dans le sens où la portée des poutrelles est la plus courte ;
- dalle pleine : chaque cellule va à la poutre la plus proche (lignes de rupture
  à 45° → triangles et trapèzes) ;
- cellule sans poutre en vis-à-vis (porte-à-faux, balcon) : poutre la plus proche,
  sinon poteau le plus proche ;
- réactions isostatiques des poutres, majorées de 15 % (2 travées) ou 10 %
  (≥ 3 travées) sur les appuis voisins de rive (BAEL B.8.1,1) ;
- cumul niveau par niveau avec la loi de dégression des charges d'exploitation
  (NF P06-001).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .model import Beam, Building, LoadSettings
from .slab import SlabMask, mask_from_rects

CONCRETE = 25.0  # kN/m³
N_BINS = 60      # discrétisation des poutres pour le calcul des moments


@dataclass
class BeamLoad:
    """Effets d'une poutre isostatique pour un niveau (kN, kN.m)."""
    g_tot: float = 0.0
    q_tot: float = 0.0
    g_m0: float = 0.0   # moment isostatique maximal sous G
    q_m0: float = 0.0
    g_rs: float = 0.0   # réaction côté départ / arrivée
    g_re: float = 0.0
    q_rs: float = 0.0
    q_re: float = 0.0
    trib_area: float = 0.0  # surface de plancher portée (m²)


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
class _UnitBeam:
    """Effets d'une charge surfacique unitaire (1 kN/m²) sur une poutre."""
    area: float = 0.0
    rs: float = 0.0
    re: float = 0.0
    m0: float = 0.0


@dataclass
class TakedownResult:
    floor_loads: dict[str, BeamLoad] = field(default_factory=dict)   # étage courant
    roof_loads: dict[str, BeamLoad] = field(default_factory=dict)    # terrasse
    columns: dict[str, list[ColumnStorey]] = field(default_factory=dict)
    lines: list[BeamLine] = field(default_factory=list)
    column_direct_area: dict[str, float] = field(default_factory=dict)
    slab_area: float = 0.0
    surface_g_floor: float = 0.0
    surface_q_floor: float = 0.0
    surface_g_roof: float = 0.0
    surface_q_roof: float = 0.0
    warnings: list[str] = field(default_factory=list)


def degression_coef(m: int) -> float:
    """Coefficient appliqué à Q1+…+Qm (m étages sous la terrasse), NF P06-001."""
    table = {0: 1.0, 1: 1.0, 2: 0.95, 3: 0.90, 4: 0.85}
    return table.get(m, (3 + m) / (2 * m))


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


def slab_mask(bld: Building) -> SlabMask | None:
    if bld.slab:
        return SlabMask.from_dict(bld.slab)
    cols = bld.column_map()
    rects = []
    for p in bld.panels:
        c = cols[p.corners[0]]
        rects.append((c.x, c.y, c.x + p.lx, c.y + p.ly))
    return mask_from_rects(rects) if rects else None


def distribute(bld: Building, mask: SlabMask, floor_type: str) -> tuple[dict[str, _UnitBeam], dict[str, float]]:
    """Répartit une charge surfacique unitaire entre poutres et poteaux."""
    cols = bld.column_map()
    cx, cy = mask.centers()
    a = mask.res ** 2
    n = len(cx)
    INF = np.inf
    # meilleurs candidats : distance et indice de poutre, dans les 4 directions
    best = {k: (np.full(n, INF), np.full(n, -1)) for k in ("below", "above", "left", "right")}
    beams = list(bld.beams)
    geo = []
    for k, b in enumerate(beams):
        c1, c2 = cols[b.start], cols[b.end]
        if b.direction == "X":
            lo, hi, pos = min(c1.x, c2.x), max(c1.x, c2.x), (c1.y + c2.y) / 2
            cover = (cx >= lo) & (cx <= hi)
            d = cy - pos
            sides = (("below", d >= 0, d), ("above", d < 0, -d))
        else:
            lo, hi, pos = min(c1.y, c2.y), max(c1.y, c2.y), (c1.x + c2.x) / 2
            cover = (cy >= lo) & (cy <= hi)
            d = cx - pos
            sides = (("left", d >= 0, d), ("right", d < 0, -d))
        geo.append((lo, hi))
        for key, side, dist in sides:
            bd, bi = best[key]
            upd = cover & side & (dist < bd)
            bd[upd] = dist[upd]
            bi[upd] = k

    dB, iB = best["below"]
    dA, iA = best["above"]
    dL, iL = best["left"]
    dR, iR = best["right"]
    gap_x = dB + dA   # portée entre poutres X (selon Y)
    gap_y = dL + dR
    choice = np.full(n, -1)
    if floor_type == "corps_creux":
        use_x = gap_x <= gap_y
        both_x, both_y = np.isfinite(gap_x), np.isfinite(gap_y)
        pick_x = both_x & (use_x | ~both_y)
        pick_y = both_y & ~pick_x
        choice[pick_x] = np.where(dB[pick_x] <= dA[pick_x], iB[pick_x], iA[pick_x])
        choice[pick_y] = np.where(dL[pick_y] <= dR[pick_y], iL[pick_y], iR[pick_y])
    # dalle pleine, ou cellules sans paire de poutres : poutre la plus proche
    rest = choice < 0
    # égalités (diagonales à 45°) partagées équitablement entre poutres X et Y
    col_idx = np.round((cx - mask.x0) / mask.res - 0.5).astype(int)
    bias = 1e-9 * (col_idx % 2)
    stack_d = np.vstack([dB + bias, dA + bias, dL + 1e-9 - bias, dR + 1e-9 - bias])
    stack_i = np.vstack([iB, iA, iL, iR])
    k_min = np.argmin(stack_d, axis=0)
    d_min = stack_d[k_min, np.arange(n)]
    near = rest & np.isfinite(d_min) & (d_min <= 3.0)
    choice[near] = stack_i[k_min[near], np.nonzero(near)[0]]

    unit: dict[str, _UnitBeam] = {b.id: _UnitBeam() for b in beams}
    for k, b in enumerate(beams):
        sel = choice == k
        if not sel.any():
            continue
        lo, hi = geo[k]
        L = hi - lo
        t = (cx[sel] if b.direction == "X" else cy[sel]) - lo
        c1 = cols[b.start]
        start_is_lo = (c1.x if b.direction == "X" else c1.y) <= lo + 1e-9
        area = float(a * sel.sum())
        r_hi = float(a * t.sum() / L)
        r_lo = area - r_hi
        # moment maximal (charges ponctuelles regroupées par tranches)
        hist, edges = np.histogram(t, bins=N_BINS, range=(0, L))
        loads = hist * a
        mid = (edges[:-1] + edges[1:]) / 2
        xs = edges
        m = r_lo * xs - np.array([np.sum(loads * np.clip(x - mid, 0, None)) for x in xs])
        ub = unit[b.id]
        ub.area = area
        ub.rs, ub.re = (r_lo, r_hi) if start_is_lo else (r_hi, r_lo)
        ub.m0 = float(m.max())

    # Cellules restantes : poteau le plus proche
    direct: dict[str, float] = {c.id: 0.0 for c in bld.columns}
    rest = choice < 0
    if rest.any() and bld.columns:
        px = np.array([c.x for c in bld.columns])
        py = np.array([c.y for c in bld.columns])
        rx, ry = cx[rest], cy[rest]
        nearest = np.argmin((rx[:, None] - px[None, :]) ** 2 + (ry[:, None] - py[None, :]) ** 2, axis=1)
        for idx, cnt in zip(*np.unique(nearest, return_counts=True)):
            direct[bld.columns[idx].id] += float(cnt * a)
    return unit, direct


def compute_takedown(bld: Building, ls: LoadSettings) -> TakedownResult:
    res = TakedownResult()
    cols = bld.column_map()
    beams = bld.beam_map()
    res.lines = beam_lines(bld)

    res.surface_g_floor = ls.g_floor + ls.g_finishes
    res.surface_q_floor = ls.q_floor
    res.surface_g_roof = ls.g_floor + ls.g_roof_extra
    res.surface_q_roof = ls.q_roof

    mask = slab_mask(bld)
    if mask is None:
        res.warnings.append("Aucun contour de plancher : seules les charges propres des éléments sont prises en compte.")
        unit = {b.id: _UnitBeam() for b in bld.beams}
        direct = {c.id: 0.0 for c in bld.columns}
    else:
        res.slab_area = mask.area
        unit, direct = distribute(bld, mask, ls.floor_type)
    res.column_direct_area = direct
    if sum(direct.values()) > 0.05 * max(res.slab_area, 1e-9):
        res.warnings.append(
            f"{sum(direct.values()):.1f} m² de plancher sans poutre en vis-à-vis, reportés directement sur le "
            "poteau le plus proche (vérifier les porte-à-faux et ajouter des poutres si nécessaire)."
        )

    # Poutres de rive : peu de plancher d'un côté → façade
    def level_loads(g: float, q: float, roof: bool) -> dict[str, BeamLoad]:
        out: dict[str, BeamLoad] = {}
        for b in bld.beams:
            L = b.length(cols)
            u = unit[b.id]
            w = CONCRETE * b.b * b.h
            if not roof and ls.facade_load and b.id in edge_beams:
                w += ls.facade_load
            out[b.id] = BeamLoad(
                g_tot=g * u.area + w * L, q_tot=q * u.area,
                g_m0=g * u.m0 + w * L ** 2 / 8, q_m0=q * u.m0,
                g_rs=g * u.rs + w * L / 2, g_re=g * u.re + w * L / 2,
                q_rs=q * u.rs, q_re=q * u.re, trib_area=u.area,
            )
        return out

    edge_beams = _edge_beams(bld, mask)
    res.floor_loads = level_loads(res.surface_g_floor, res.surface_q_floor, roof=False)
    res.roof_loads = level_loads(res.surface_g_roof, res.surface_q_roof, roof=True)

    # Coefficients de continuité sur les appuis
    coef: dict[tuple[str, str], float] = {}
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

    def reactions(loads: dict[str, BeamLoad], g: float, q: float) -> dict[str, tuple[float, float]]:
        r = {c.id: [direct[c.id] * g, direct[c.id] * q] for c in bld.columns}
        for b in bld.beams:
            bl = loads[b.id]
            for cid, rg, rq in ((b.start, bl.g_rs, bl.q_rs), (b.end, bl.g_re, bl.q_re)):
                f = coef.get((b.id, cid), 1.0)
                r[cid][0] += f * rg
                r[cid][1] += f * rq
        return {k: (v[0], v[1]) for k, v in r.items()}

    r_floor = reactions(res.floor_loads, res.surface_g_floor, res.surface_q_floor)
    r_roof = reactions(res.roof_loads, res.surface_g_roof, res.surface_q_roof)

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
            q_cum = q_list[0] + degression_coef(m) * sum(q_list[1:]) if (ls.degression and m >= 2) else q_raw
            storeys.append(ColumnStorey(storey=level, g=g_cum, q=q_cum, q_raw=q_raw))
        res.columns[c.id] = storeys

    # Contrôle des conditions de la méthode forfaitaire
    for line in res.lines:
        spans = [beams[b].length(cols) for b in line.beams]
        for x, y in zip(spans, spans[1:]):
            if not 0.8 <= x / y <= 1.25:
                res.warnings.append(
                    f"File {'-'.join(line.supports)} : rapport de portées {x:.2f}/{y:.2f} hors [0,8 ; 1,25] — "
                    "moments forfaitaires à confirmer par un calcul de continuité (Caquot)."
                )
                break
    if ls.q_floor > max(2 * res.surface_g_floor, 5.0):
        res.warnings.append("Q > max(2G ; 5 kN/m²) : la méthode forfaitaire n'est pas applicable.")
    return res


def _edge_beams(bld: Building, mask: SlabMask | None) -> set[str]:
    """Poutres de façade : plancher d'un seul côté."""
    if mask is None:
        return set()
    cols = bld.column_map()
    out = set()
    ny, nx = mask.mask.shape

    def inside(x: float, y: float) -> bool:
        i, j = int((x - mask.x0) / mask.res), int((y - mask.y0) / mask.res)
        return 0 <= i < nx and 0 <= j < ny and bool(mask.mask[j, i])

    for b in bld.beams:
        c1, c2 = cols[b.start], cols[b.end]
        mx, my = (c1.x + c2.x) / 2, (c1.y + c2.y) / 2
        off = 0.6
        sides = ((mx, my - off), (mx, my + off)) if b.direction == "X" else ((mx - off, my), (mx + off, my))
        if sum(inside(*p) for p in sides) <= 1:
            out.add(b.id)
    return out
