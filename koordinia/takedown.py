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
from .zones import cell_loads, zone_objects

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
    storey: int          # 1 = étage le plus bas (le plus chargé)
    g: float             # kN cumulés en pied de poteau
    q: float             # kN cumulés après dégression
    q_raw: float         # kN cumulés sans dégression
    b: float = 0.0       # section du poteau à cet étage (m)
    h: float = 0.0
    height: float = 0.0  # hauteur d'étage (m)
    origin: str = ""     # « » ; « naissant » (porté par une poutre / un poteau) ; « sur mur »


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
class StoreyLoads:
    index: int                    # 0 = étage le plus bas
    name: str
    floor_name: str
    roof: bool
    beam_loads: dict[str, "BeamLoad"] = field(default_factory=dict)
    lines: list["BeamLine"] = field(default_factory=list)
    direct_area: dict[str, float] = field(default_factory=dict)
    slab_area: float = 0.0
    point_loads: dict[str, list[tuple[float, float, float, str]]] = field(default_factory=dict)  # poutre → (t, G, Q, poteau)
    zones: list[tuple] = field(default_factory=list)       # (zone, surface, G moyen, Q moyen)
    balconies: list[tuple] = field(default_factory=list)   # (zone, surface, porte-à-faux, G, Q)


@dataclass
class WallSupport:
    """Poteau d'un étage reposant sur un mur de l'étage inférieur."""
    column_id: str
    storey: int        # indice (1 = bas) de l'étage dont le mur reçoit la charge
    x: float
    y: float
    g: float
    q: float


@dataclass
class TakedownResult:
    storeys: list[StoreyLoads] = field(default_factory=list)          # du bas vers le haut
    columns: dict[str, list[ColumnStorey]] = field(default_factory=dict)
    wall_supports: list[WallSupport] = field(default_factory=list)
    surface_g_floor: float = 0.0
    surface_q_floor: float = 0.0
    surface_g_roof: float = 0.0
    surface_q_roof: float = 0.0
    warnings: list[str] = field(default_factory=list)

    # --- accès simplifiés (plan unique) ---
    @property
    def roof_loads(self) -> dict[str, "BeamLoad"]:
        return self.storeys[-1].beam_loads

    @property
    def floor_loads(self) -> dict[str, "BeamLoad"]:
        return self.storeys[-2].beam_loads if len(self.storeys) > 1 else self.storeys[-1].beam_loads

    @property
    def lines(self) -> list["BeamLine"]:
        return self.storeys[-1].lines

    @property
    def slab_area(self) -> float:
        return self.storeys[-1].slab_area

    @property
    def column_direct_area(self) -> dict[str, float]:
        return self.storeys[-1].direct_area


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


def distribute(bld: Building, mask: SlabMask, floor_type: str, weights: list[np.ndarray] | None = None):
    """Répartit les charges du plancher entre poutres et poteaux.

    Sans `weights` : charge surfacique unitaire → (poutres, poteaux).
    Avec `weights` (charge par cellule, kN/m², dans l'ordre de `mask.centers()`) :
    une paire (poutres, poteaux) par jeu de poids.
    """
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

    rest = choice < 0
    nearest = None
    if rest.any() and bld.columns:
        px = np.array([c.x for c in bld.columns])
        py = np.array([c.y for c in bld.columns])
        rx, ry = cx[rest], cy[rest]
        nearest = np.argmin((rx[:, None] - px[None, :]) ** 2 + (ry[:, None] - py[None, :]) ** 2, axis=1)

    def accumulate(wt: np.ndarray):
        unit: dict[str, _UnitBeam] = {b.id: _UnitBeam() for b in beams}
        for k, b in enumerate(beams):
            sel = choice == k
            if not sel.any():
                continue
            lo, hi = geo[k]
            L = hi - lo
            t = (cx[sel] if b.direction == "X" else cy[sel]) - lo
            w = wt[sel] * a
            c1 = cols[b.start]
            start_is_lo = (c1.x if b.direction == "X" else c1.y) <= lo + 1e-9
            total = float(w.sum())
            r_hi = float((w * t).sum() / L)
            r_lo = total - r_hi
            # moment maximal (charges ponctuelles regroupées par tranches)
            loads, edges = np.histogram(t, bins=N_BINS, range=(0, L), weights=w)
            mid = (edges[:-1] + edges[1:]) / 2
            m = r_lo * edges - np.array([np.sum(loads * np.clip(x - mid, 0, None)) for x in edges])
            ub = unit[b.id]
            ub.area = total
            ub.rs, ub.re = (r_lo, r_hi) if start_is_lo else (r_hi, r_lo)
            ub.m0 = float(m.max())
        # Cellules restantes : poteau le plus proche
        direct: dict[str, float] = {c.id: 0.0 for c in bld.columns}
        if nearest is not None:
            wr = wt[rest] * a
            for idx in np.unique(nearest):
                direct[bld.columns[idx].id] += float(wr[nearest == idx].sum())
        return unit, direct

    if weights is None:
        return accumulate(np.ones(n))
    return [accumulate(np.asarray(wt, dtype=float)) for wt in weights]


def compute_takedown(model, ls: LoadSettings) -> TakedownResult:
    """Descente de charges d'un plan unique (Building) ou d'un projet multi-niveaux (Project)."""
    from .project import Project

    proj = model if isinstance(model, Project) else Project.from_building(model)
    return compute_project(proj, ls)


def _on_wall(plan: Building, x: float, y: float, tol: float = 0.15) -> bool:
    for x0, y0, x1, y1, t in plan.walls:
        if abs(y1 - y0) < 1e-6:  # mur horizontal
            if min(x0, x1) - tol <= x <= max(x0, x1) + tol and abs(y - y0) <= t / 2 + tol:
                return True
        elif abs(x1 - x0) < 1e-6:
            if min(y0, y1) - tol <= y <= max(y0, y1) + tol and abs(x - x0) <= t / 2 + tol:
                return True
    return False


def _beam_under(plan: Building, x: float, y: float, tol: float = 0.35) -> tuple[str, float] | None:
    """Poutre passant sous le point (x, y) : (id, abscisse depuis le poteau de départ)."""
    cols = plan.column_map()
    best = None
    for b in plan.beams:
        c1, c2 = cols[b.start], cols[b.end]
        L = b.length(cols)
        if L <= 0:
            continue
        ux, uy = (c2.x - c1.x) / L, (c2.y - c1.y) / L
        t = (x - c1.x) * ux + (y - c1.y) * uy
        d = abs((x - c1.x) * uy - (y - c1.y) * ux)
        if 0.05 * L <= t <= 0.95 * L and d <= tol and (best is None or d < best[2]):
            best = (b.id, t, d)
    return (best[0], best[1]) if best else None


def compute_project(proj, ls: LoadSettings) -> TakedownResult:
    res = TakedownResult()
    res.surface_g_floor = ls.g_floor + ls.g_finishes
    res.surface_q_floor = ls.q_floor
    res.surface_g_roof = ls.g_floor + ls.g_roof_extra
    res.surface_q_roof = ls.q_roof
    N = proj.n
    cache: dict[int, tuple] = {}

    def unit_of(plan: Building, roof: bool, g_def: float, q_def: float):
        key = (id(plan), roof)
        if key not in cache:
            mask = slab_mask(plan)
            balconies: list[tuple] = []
            zone_rows: list[tuple] = []
            if mask is None:
                empty = ({b.id: _UnitBeam() for b in plan.beams}, {c.id: 0.0 for c in plan.columns})
                parts = [empty, empty, empty]
                area = 0.0
            else:
                eff, g_w, q_w, sels = cell_loads(mask, zone_objects(plan), g_def, q_def, ls.g_floor, roof)
                emask = SlabMask(mask.res, mask.x0, mask.y0, eff)
                parts = distribute(plan, emask, ls.floor_type, weights=[g_w, q_w, np.ones(len(g_w))])
                area = emask.area
                cx, cy = emask.centers()
                for z, sel in sels:
                    zone_rows.append((z, float(sel.sum()) * mask.res ** 2, float(g_w[sel].mean()),
                                      float(q_w[sel].mean())))
                    if z.type == "balcon":
                        balconies.append((z, float(sel.sum()) * mask.res ** 2,
                                          _cantilever_length(plan, cx[sel], cy[sel]),
                                          float(g_w[sel].mean()), float(q_w[sel].mean())))
            cache[key] = (parts, area, _edge_beams(plan, mask), beam_lines(plan), zone_rows, balconies)
        return cache[key]

    # charge arrivant en tête de chaque poteau de l'étage courant : id → (G, vecteur Q par plancher)
    carried: dict[str, tuple[float, np.ndarray, float, float]] = {}
    storey_loads: list[StoreyLoads] = [None] * N  # type: ignore[list-item]
    col_results: dict[str, list[ColumnStorey]] = {}

    for s in range(N - 1, -1, -1):
        st = proj.storeys[s]
        plan = st.plan
        roof = s == N - 1
        g_s = res.surface_g_roof if roof else res.surface_g_floor
        q_s = res.surface_q_roof if roof else res.surface_q_floor
        parts, area, edges, lines, zone_rows, balconies = unit_of(plan, roof, g_s, q_s)
        (ug, dg), (uq, dq), (ua, da) = parts
        cols = plan.column_map()
        sl = StoreyLoads(s, st.name, proj.floor_label(s), roof, lines=lines, direct_area=da, slab_area=area,
                         zones=zone_rows, balconies=balconies)
        direct = da
        if area and sum(direct.values()) > 0.05 * area and not (proj.single_plan and s < N - 1):
            res.warnings.append(
                f"{sl.floor_name} : {sum(direct.values()):.1f} m² de plancher sans poutre en vis-à-vis, reportés "
                "directement sur le poteau le plus proche (vérifier les porte-à-faux, ajouter des poutres)."
            )

        # --- poteaux de l'étage supérieur qui ne continuent pas ici
        extra_g: dict[str, float] = {c.id: 0.0 for c in plan.columns}
        extra_q: dict[str, np.ndarray] = {c.id: np.zeros(N) for c in plan.columns}
        points: dict[str, list[tuple[float, float, np.ndarray, str]]] = {}
        for cid, (g, qv, x, y) in carried.items():
            if cid in cols:
                extra_g[cid] += g
                extra_q[cid] += qv
                continue
            if _on_wall(plan, x, y):
                res.wall_supports.append(WallSupport(cid, s + 1, x, y, float(g), float(qv.sum())))
                res.warnings.append(f"Poteau {cid} ({proj.storeys[s + 1].name}) : repose sur un mur de "
                                    f"{st.name} — charge transmise au mur (voile à vérifier, semelle filante).")
                continue
            under = _beam_under(plan, x, y)
            if under:
                bid, t = under
                points.setdefault(bid, []).append((t, g, qv, cid))
                res.warnings.append(f"Poteau naissant {cid} ({proj.storeys[s + 1].name}) porté par la poutre "
                                    f"{bid} du {sl.floor_name} : POUTRE DE TRANSFERT à étudier.")
            elif plan.columns:
                near = min(plan.columns, key=lambda c: (c.x - x) ** 2 + (c.y - y) ** 2)
                dist = ((near.x - x) ** 2 + (near.y - y) ** 2) ** 0.5
                extra_g[near.id] += g
                extra_q[near.id] += qv
                res.warnings.append(f"Poteau naissant {cid} ({proj.storeys[s + 1].name}) sans poutre dessous : "
                                    f"charge reportée sur {near.id} à {dist:.1f} m — structure à revoir.")

        # --- charges des poutres
        beam_q_vec: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for b in plan.beams:
            L = b.length(cols)
            u, v = ug[b.id], uq[b.id]
            w = CONCRETE * b.b * b.h
            if not roof and ls.facade_load and b.id in edges:
                w += ls.facade_load
            bl = BeamLoad(
                g_tot=u.area + w * L, q_tot=v.area,
                g_m0=u.m0 + w * L ** 2 / 8, q_m0=v.m0,
                g_rs=u.rs + w * L / 2, g_re=u.re + w * L / 2,
                q_rs=v.rs, q_re=v.re, trib_area=ua[b.id].area,
            )
            rs_v, re_v = np.zeros(N), np.zeros(N)
            rs_v[s], re_v[s] = v.rs, v.re
            for t, g, qv, cid in points.get(b.id, []):
                a, bb = t, L - t
                qsum = float(qv.sum())
                bl.g_tot += g
                bl.q_tot += qsum
                bl.g_m0 += g * a * bb / L
                bl.q_m0 += qsum * a * bb / L
                bl.g_rs += g * bb / L
                bl.g_re += g * a / L
                bl.q_rs += qsum * bb / L
                bl.q_re += qsum * a / L
                rs_v += qv * bb / L
                re_v += qv * a / L
                sl.point_loads.setdefault(b.id, []).append((round(t, 2), g, qsum, cid))
            sl.beam_loads[b.id] = bl
            beam_q_vec[b.id] = (rs_v, re_v)

        # --- coefficients de continuité
        coef: dict[tuple[str, str], float] = {}
        if ls.continuity:
            for line in lines:
                n = len(line.beams)
                targets = {1: 1.15} if n == 2 else ({1: 1.10, n - 1: 1.10} if n >= 3 else {})
                for idx, f in targets.items():
                    sup = line.supports[idx]
                    for bid in (line.beams[idx - 1], line.beams[idx]):
                        coef[(bid, sup)] = f

        # --- poteaux de l'étage
        new_carried: dict[str, tuple[float, np.ndarray, float, float]] = {}
        g_col = {c.id: dg[c.id] + extra_g[c.id] for c in plan.columns}
        q_col = {c.id: extra_q[c.id].copy() for c in plan.columns}
        for c in plan.columns:
            q_col[c.id][s] += dq[c.id]
        for b in plan.beams:
            bl = sl.beam_loads[b.id]
            rs_v, re_v = beam_q_vec[b.id]
            for cid, rg, rq in ((b.start, bl.g_rs, rs_v), (b.end, bl.g_re, re_v)):
                f = coef.get((b.id, cid), 1.0)
                g_col[cid] += f * rg
                q_col[cid] += f * rq
        for c in plan.columns:
            g = float(g_col[c.id] + CONCRETE * c.b * c.h * st.height)
            qv = q_col[c.id]
            q_raw = float(qv.sum())
            # dégression : Q0 = terrasse, Q1… = planchers inférieurs portés
            m = N - 1 - s
            if ls.degression and m >= 2:
                q = float(qv[N - 1] + degression_coef(m) * qv[s:N - 1].sum())
            else:
                q = q_raw
            origin = "" if (s == N - 1 or c.id in carried) else "départ"
            col_results.setdefault(c.id, []).append(
                ColumnStorey(storey=s + 1, g=g, q=q, q_raw=q_raw, b=c.b, h=c.h, height=st.height, origin=origin))
            new_carried[c.id] = (g, qv, c.x, c.y)
        carried = new_carried
        storey_loads[s] = sl

    res.storeys = storey_loads
    res.columns = col_results

    # Contrôle des conditions de la méthode forfaitaire (une fois par plan)
    seen: set[int] = set()
    for st in proj.storeys:
        if id(st.plan) in seen:
            continue
        seen.add(id(st.plan))
        cols = st.plan.column_map()
        beams = st.plan.beam_map()
        for line in beam_lines(st.plan):
            spans = [beams[b].length(cols) for b in line.beams]
            for x, y in zip(spans, spans[1:]):
                if not 0.8 <= x / y <= 1.25:
                    res.warnings.append(
                        f"{'' if proj.single_plan else st.name + ' — '}File {'-'.join(line.supports)} : rapport de "
                        f"portées {x:.2f}/{y:.2f} hors [0,8 ; 1,25] — moments forfaitaires à confirmer (Caquot)."
                    )
                    break
    if ls.q_floor > max(2 * res.surface_g_floor, 5.0):
        res.warnings.append("Q > max(2G ; 5 kN/m²) : la méthode forfaitaire n'est pas applicable.")
    return res


def _cantilever_length(plan: Building, x: np.ndarray, y: np.ndarray) -> float:
    """Porte-à-faux d'un balcon : distance (95e centile) des cellules au nu de la poutre la plus proche."""
    if len(x) == 0 or not plan.beams:
        return 0.0
    cols = plan.column_map()
    best = np.full(len(x), np.inf)
    half = np.zeros(len(x))
    for b in plan.beams:
        c1, c2 = cols[b.start], cols[b.end]
        dx, dy = c2.x - c1.x, c2.y - c1.y
        L2 = dx * dx + dy * dy
        t = np.clip(((x - c1.x) * dx + (y - c1.y) * dy) / L2, 0, 1)
        d = np.hypot(x - (c1.x + t * dx), y - (c1.y + t * dy))
        upd = d < best
        best[upd] = d[upd]
        half[upd] = b.b / 2
    return float(max(0.0, np.percentile(best - half, 95)))


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
