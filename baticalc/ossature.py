"""Proposition d'ossature à partir des axes des murs (plans d'architecte sans poteaux dessinés).

Règles de pré-conception (maçonnerie chaînée, Côte d'Ivoire / Afrique de l'Ouest) :
- poteaux aux angles, aux croisements et aux extrémités libres des murs ;
- poteaux intermédiaires quand deux poteaux voisins sur un même mur sont à plus de `max_span` ;
- poutres (chaînage haut) sur tous les murs, entre poteaux consécutifs ;
- nœuds voisins de moins de `merge` fusionnés (murs dessinés avec de petits décalages).
"""
from __future__ import annotations

import math

import numpy as np

from .model import Beam, Building, Column
from .slab import SlabMask


def structure_from_walls(walls: list[tuple[float, float, float, float]], *, max_span: float = 4.5,
                         merge: float = 0.45, col: tuple[float, float] = (0.20, 0.20),
                         beam: tuple[float, float] = (0.20, 0.30), footprint: list[tuple] | None = None,
                         res: float = 0.10, extra_columns: list[tuple[float, float]] = (),
                         avoid: list[tuple[float, float, float, float]] = (),
                         axes: tuple[list[float], list[float]] = ([], []), long_span: float = 7.5,
                         min_free: float = 2.0, min_dist: float = 0.6) -> Building:
    """`walls` : axes orthogonaux (x0, y0, x1, y1) en m ; `footprint` : rectangles (x0, y0, x1, y1)
    couverts par le plancher ou la toiture (sinon enveloppe des murs) ; `avoid` : baies (segments sur
    les axes des murs) où l'on ne place pas de poteau intermédiaire ; `axes` : files du plan (x, y) sur
    lesquelles on cale de préférence les poteaux intermédiaires.

    Un mur donné avec un 5e terme "v" est virtuel (poutre sans mur dessous : plancher à recouper, mur de
    l'étage supérieur) : pas de poteau à ses extrémités libres ni de poteau intermédiaire sous `long_span`
    (on ne place pas de poteau au milieu d'une pièce)."""
    W = []
    virt = [len(w) > 4 and w[4] == "v" for w in walls]
    for x0, y0, x1, y1, *_ in walls:
        if abs(x1 - x0) >= abs(y1 - y0):
            W.append(("H", min(x0, x1), max(x0, x1), (y0 + y1) / 2))
        else:
            W.append(("V", min(y0, y1), max(y0, y1), (x0 + x1) / 2))
    # 0) alignement des murs voisins sur un même axe (petits décalages de dessin)
    for kind in ("H", "V"):
        vals = sorted({w[3] for w in W if w[0] == kind})
        groups: list[list[float]] = []
        for v in vals:
            if groups and v - groups[-1][-1] <= 0.30:
                groups[-1].append(v)
            else:
                groups.append([v])
        snap = {v: float(np.mean(g)) for g in groups for v in g}
        W = [(k, a, b, snap[c]) if k == kind else (k, a, b, c) for k, a, b, c in W]
    # 1) nœuds : extrémités et intersections
    pts: list[tuple[float, float]] = list(extra_columns)
    free: list[tuple[float, float]] = []          # extrémités de murs (peut-être libres)
    for (k, a, b, c), v in zip(W, virt):
        if not v:
            free += [(a, c), (b, c)] if k == "H" else [(c, a), (c, b)]
    for i, (ka, a0, a1, ac) in enumerate(W):
        for j, (kb, b0, b1, bc) in enumerate(W[i + 1:], start=i + 1):
            if ka == kb or (virt[i] and virt[j]):
                continue
            h, v = ((a0, a1, ac), (b0, b1, bc)) if ka == "H" else ((b0, b1, bc), (a0, a1, ac))
            x, y = v[2], h[2]
            if h[0] - merge <= x <= h[1] + merge and v[0] - merge <= y <= v[1] + merge:
                pts.append((x, y))
    # 2) fusion des nœuds voisins
    nodes: list[list] = []
    for (x, y), fixed in [(p, True) for p in pts] + [(p, False) for p in free]:
        for n in nodes:
            if abs(n[0] - x) <= merge and abs(n[1] - y) <= merge:
                n[2].append((x, y))
                n[3] = n[3] or fixed
                break
        else:
            nodes.append([x, y, [(x, y)], fixed])
    fixed_flag = [n[3] for n in nodes]
    nodes = [[float(np.mean([p[0] for p in n[2]])), float(np.mean([p[1] for p in n[2]]))] for n in nodes]

    for n in nodes:   # recalage exact sur les axes des murs porteurs du nœud
        hs = [w[3] for w in W if w[0] == "H" and abs(n[1] - w[3]) <= merge and w[1] - merge <= n[0] <= w[2] + merge]
        vs = [w[3] for w in W if w[0] == "V" and abs(n[0] - w[3]) <= merge and w[1] - merge <= n[1] <= w[2] + merge]
        if hs:
            n[1] = min(hs, key=lambda v: abs(v - n[1]))
        if vs:
            n[0] = min(vs, key=lambda v: abs(v - n[0]))

    def on_wall(n, w, perp=merge):
        k, a, b, c = w
        return (abs(n[1] - c) <= perp and a - merge <= n[0] <= b + merge) if k == "H" else \
            (abs(n[0] - c) <= perp and a - merge <= n[1] <= b + merge)

    # extrémité libre d'un mur : poteau seulement à plus de `min_free` du dernier appui sur ce mur
    # (pas de poteau au bout d'un trumeau ou d'un retour de cloison)
    keep = []
    for i, n in enumerate(nodes):
        if fixed_flag[i]:
            keep.append(True)
            continue
        ok = False
        for w in W:
            if not on_wall(n, w):
                continue
            k = w[0]
            pos = n[0] if k == "H" else n[1]
            others = [(m[0] if k == "H" else m[1]) for j, m in enumerate(nodes) if fixed_flag[j] and on_wall(m, w)]
            d = min((abs(o - pos) for o in others), default=w[2] - w[1])
            ok = ok or d >= min_free
        keep.append(ok)
    nodes = [n for n, kp in zip(nodes, keep) if kp]

    # 3) poteaux intermédiaires sur les longues portées, alignés si possible sur les files existantes
    for w, v in zip(W, virt):
        k = w[0]
        along = sorted(((n[0] if k == "H" else n[1]), i) for i, n in enumerate(nodes) if on_wall(n, w))
        files = sorted({round(n[0] if k == "H" else n[1], 3) for n in nodes})
        ax = sorted(axes[0] if k == "H" else axes[1])
        for (pa, _), (pb, _) in zip(along, along[1:]):
            cur = pa
            if v and pb - pa <= long_span:
                continue
            while pb - cur > max_span:
                cands = [f for f in ax if cur + 1.0 <= f <= min(cur + max_span, pb - 1.0)] or \
                    [f for f in files if cur + 1.0 <= f <= min(cur + max_span, pb - 1.0)]
                if cands:
                    t = max(cands)
                else:
                    m = math.ceil((pb - cur) / max_span)
                    t = cur + (pb - cur) / m
                t = _off_openings(t, w, avoid, lo=cur + 1.0, hi=min(cur + max_span, pb - 1.0))
                nodes.append([t, w[3]] if k == "H" else [w[3], t])
                cur = t
    # 3 bis) poteaux trop proches (< min_dist) : on garde celui qui porte le plus de murs
    def degree(n):
        return sum(on_wall(n, w, 0.12) for w in W)
    merged = True
    while merged:
        merged = False
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1]) < min_dist:
                    drop = j if degree(nodes[i]) >= degree(nodes[j]) else i
                    del nodes[drop]
                    merged = True
                    break
            if merged:
                break
    # 4) poteaux et poutres
    order = sorted(range(len(nodes)), key=lambda i: (-round(nodes[i][1], 1), nodes[i][0]))
    ids = {i: f"P{n + 1}" for n, i in enumerate(order)}
    columns = [Column(ids[i], round(nodes[i][0], 3), round(nodes[i][1], 3), col[0], col[1]) for i in order]
    beams: list[Beam] = []
    seen = set()
    for w in W:
        k = w[0]
        along = sorted(((nodes[i][0] if k == "H" else nodes[i][1]), i) for i in range(len(nodes))
                       if on_wall(nodes[i], w, 0.12))      # poteaux alignés sur le mur : pas de poutre biaise
        for (pa, ia), (pb, ib) in zip(along, along[1:]):
            key = tuple(sorted((ia, ib)))
            if key in seen or pb - pa < 0.3:
                continue
            seen.add(key)
            beams.append(Beam(f"B{len(beams) + 1}", ids[ia], ids[ib], beam[0], beam[1], "X" if k == "H" else "Y"))
    bld = Building(columns=columns, beams=beams, n_levels=1)
    bld.walls = [[*((w[1], w[3], w[2], w[3]) if w[0] == "H" else (w[3], w[1], w[3], w[2])), 0.20] for w in W]
    bld.grid_x = sorted({round(c.x, 2) for c in columns})
    bld.grid_y = sorted({round(c.y, 2) for c in columns})
    # 5) surface portée (plancher ou toiture)
    rects = footprint or [(min(c.x for c in columns), min(c.y for c in columns),
                           max(c.x for c in columns), max(c.y for c in columns))]
    x0 = min(r[0] for r in rects) - 0.5
    y0 = min(r[1] for r in rects) - 0.5
    nx = int(math.ceil((max(r[2] for r in rects) + 0.5 - x0) / res))
    ny = int(math.ceil((max(r[3] for r in rects) + 0.5 - y0) / res))
    m = np.zeros((ny, nx), dtype=bool)
    for a, b, c, d in rects:
        m[int(round((b - y0) / res)):int(round((d - y0) / res)), int(round((a - x0) / res)):int(round((c - x0) / res))] = True
    bld.slab = SlabMask(res, x0, y0, m).to_dict()
    bld.warnings.append(f"Ossature proposée d'après les murs : {len(columns)} poteaux {col[0] * 100:.0f}×{col[1] * 100:.0f}, "
                        f"{len(beams)} chaînages {beam[0] * 100:.0f}×{beam[1] * 100:.0f}, portée maximale {max_span:g} m "
                        "— à valider par l'ingénieur.")
    return bld


def _off_openings(t: float, w, avoid, *, lo: float, hi: float, margin: float = 0.15) -> float:
    """Décale une position `t` le long du mur `w` hors des baies (vers le bord le plus proche admissible)."""
    k, _, _, c = w
    for x0, y0, x1, y1 in avoid:
        horiz = abs(x1 - x0) >= abs(y1 - y0)
        if horiz != (k == "H") or abs((y0 if horiz else x0) - c) > 0.35:
            continue
        a, b = (min(x0, x1), max(x0, x1)) if horiz else (min(y0, y1), max(y0, y1))
        if a - margin < t < b + margin:
            opts = [v for v in (a - margin, b + margin) if lo <= v <= hi]
            if opts:
                return min(opts, key=lambda v: abs(v - t))
    return t


def beams_on_walls(columns: list[Column], walls, *, merge: float = 0.40, beam: tuple[float, float] = (0.20, 0.40),
                   start: int = 1) -> list[Beam]:
    """Poutres le long des murs (axes x0, y0, x1, y1…) entre poteaux consécutifs situés sur le mur."""
    out: list[Beam] = []
    seen = set()
    for w in walls:
        x0, y0, x1, y1 = w[:4]
        horiz = abs(x1 - x0) >= abs(y1 - y0)
        c = (y0 + y1) / 2 if horiz else (x0 + x1) / 2
        a, b = (min(x0, x1), max(x0, x1)) if horiz else (min(y0, y1), max(y0, y1))
        on = sorted(((col.x if horiz else col.y), col.id) for col in columns
                    if abs((col.y if horiz else col.x) - c) <= merge and a - merge <= (col.x if horiz else col.y) <= b + merge)
        for (pa, ia), (pb, ib) in zip(on, on[1:]):
            key = tuple(sorted((ia, ib)))
            if key in seen or pb - pa < 0.3:
                continue
            seen.add(key)
            out.append(Beam(f"B{start + len(out)}", ia, ib, beam[0], beam[1], "X" if horiz else "Y"))
    return out


# ---------------------------------------------------------------------------- plancher sans appui
def _raster_beams(bld: Building, mask: SlabMask) -> np.ndarray:
    ny, nx = mask.mask.shape
    out = np.zeros((ny, nx), dtype=bool)
    cols = bld.column_map()
    for b in bld.beams:
        c1, c2 = cols[b.start], cols[b.end]
        n = int(max(abs(c2.x - c1.x), abs(c2.y - c1.y)) / mask.res * 2) + 2
        for t in np.linspace(0.0, 1.0, n):
            i = int((c1.y + t * (c2.y - c1.y) - mask.y0) / mask.res)
            j = int((c1.x + t * (c2.x - c1.x) - mask.x0) / mask.res)
            if 0 <= i < ny and 0 <= j < nx:
                out[i, j] = True
    return out


def _ray_dist(sup: np.ndarray, inside: np.ndarray, res: float, cantilever: float) -> np.ndarray:
    """Distance (m) au plus proche appui vers les indices décroissants de chaque ligne ; 0 si le bord du
    plancher est à moins de `cantilever` (porte-à-faux admis), +inf sinon."""
    ny, nx = sup.shape
    idx = np.broadcast_to(np.arange(nx), (ny, nx))
    last_sup = np.maximum.accumulate(np.where(sup, idx, -1), axis=1)
    last_edge = np.maximum.accumulate(np.where(~inside, idx, -1), axis=1)
    d = np.where(last_sup >= 0, (idx - last_sup) * res, np.inf)
    edge_first = last_edge > last_sup
    de = (idx - last_edge) * res
    d = np.where(edge_first, np.where(de <= cantilever, 0.0, np.inf), d)
    return d


def unsupported(bld: Building, mask: SlabMask, *, slab_span: float = 5.5, cantilever: float = 1.5) -> np.ndarray:
    """Cellules du plancher dont la petite portée entre poutres dépasse `slab_span`."""
    sup = _raster_beams(bld, mask)
    m = mask.mask
    dl = _ray_dist(sup, m, mask.res, cantilever)
    dr = _ray_dist(sup[:, ::-1], m[:, ::-1], mask.res, cantilever)[:, ::-1]
    dd = _ray_dist(sup.T, m.T, mask.res, cantilever).T
    du = _ray_dist(sup.T[:, ::-1], m.T[:, ::-1], mask.res, cantilever)[:, ::-1].T
    span = np.minimum(dl + dr, dd + du)
    return m & ~sup & (span > slab_span)


def _largest_region(a: np.ndarray) -> tuple[int, int, int, int, int] | None:
    """Plus grande composante connexe (4-voisinage) : (n, i0, j0, i1, j1)."""
    from collections import deque

    seen = np.zeros_like(a)
    best = None
    for i0, j0 in zip(*np.nonzero(a)):
        if seen[i0, j0]:
            continue
        q = deque([(i0, j0)])
        seen[i0, j0] = True
        n, bi0, bj0, bi1, bj1 = 0, i0, j0, i0, j0
        while q:
            i, j = q.popleft()
            n += 1
            bi0, bj0, bi1, bj1 = min(bi0, i), min(bj0, j), max(bi1, i), max(bj1, j)
            for u, v in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= u < a.shape[0] and 0 <= v < a.shape[1] and a[u, v] and not seen[u, v]:
                    seen[u, v] = True
                    q.append((u, v))
        if best is None or n > best[0]:
            best = (n, bi0, bj0, bi1, bj1)
    return best


def perimeter_walls(mask: SlabMask, walls, *, min_len: float = 1.0, near: float = 0.45) -> list[tuple]:
    """Rives du plancher (contour orthogonal) non doublées par un mur : poutres de rive."""
    from .slab import outline_segments

    out = []
    for x0, y0, x1, y1 in outline_segments(mask):
        horiz = abs(x1 - x0) >= abs(y1 - y0)
        L = abs(x1 - x0) + abs(y1 - y0)
        if L < min_len:
            continue
        a, b = (min(x0, x1), max(x0, x1)) if horiz else (min(y0, y1), max(y0, y1))
        c = y0 if horiz else x0
        covered = 0.0
        for w in walls:
            wh = abs(w[2] - w[0]) >= abs(w[3] - w[1])
            if wh != horiz:
                continue
            wc = (w[1] + w[3]) / 2 if wh else (w[0] + w[2]) / 2
            if abs(wc - c) > near:
                continue
            wa, wb = (min(w[0], w[2]), max(w[0], w[2])) if wh else (min(w[1], w[3]), max(w[1], w[3]))
            covered += max(0.0, min(b, wb) - max(a, wa))
        if covered < 0.5 * L:
            out.append((x0, y0, x1, y1))
    return out


def structure_on_slab(walls: list[tuple], mask: SlabMask, *, perimeter: SlabMask | None = None,
                      max_span: float = 4.5, slab_span: float = 5.5, max_iter: int = 15,
                      virtual_walls: list[tuple] = (), **kw) -> Building:
    """Ossature d'après les murs, complétée pour que tout le plancher soit porté :
    poutres de rive sur les bords sans mur, puis files de poutres et poteaux ajoutées au milieu
    des zones dont la portée de dalle dépasse `slab_span` (calées sur les files existantes)."""
    walls = [tuple(w[:4]) for w in walls]
    n_real = len(walls)
    extra = perimeter_walls(perimeter or mask, walls)
    walls = walls + extra + [(*w[:4], "v") for w in virtual_walls]
    added = len(extra)
    fp = kw.pop("footprint", None)
    bld = structure_from_walls(walls, max_span=max_span, footprint=fp, **kw)
    for _ in range(max_iter):
        un = unsupported(bld, mask, slab_span=slab_span)
        reg = _largest_region(un)
        if reg is None or reg[0] * mask.res ** 2 < 1.0:
            break
        _, i0, j0, i1, j1 = reg
        x0, x1 = mask.x0 + j0 * mask.res, mask.x0 + (j1 + 1) * mask.res
        y0, y1 = mask.y0 + i0 * mask.res, mask.y0 + (i1 + 1) * mask.res
        files_x = sorted({c.x for c in bld.columns})
        files_y = sorted({c.y for c in bld.columns})
        vertical = (x1 - x0) >= (y1 - y0)       # on recoupe la plus grande dimension
        lo, hi = (x0, x1) if vertical else (y0, y1)
        mid = (lo + hi) / 2
        inner = lambda fs: [f for f in fs if lo + (hi - lo) / 4 <= f <= hi - (hi - lo) / 4]  # noqa: E731
        axes = kw.get("axes", ([], []))
        cands = inner(axes[0] if vertical else axes[1]) or inner(files_x if vertical else files_y)
        pos = min(cands, key=lambda f: abs(f - mid)) if cands else round(mid, 2)
        # prolongement de la file jusqu'aux poutres (ou au bord) de part et d'autre de la zone
        sup = _raster_beams(bld, mask)
        ny, nx = mask.mask.shape
        if vertical:
            j = min(nx - 1, max(0, int((pos - mask.x0) / mask.res)))
            col_m, col_s = mask.mask[:, j], sup[:, j]
            a, b = i0, i1
        else:
            i = min(ny - 1, max(0, int((pos - mask.y0) / mask.res)))
            col_m, col_s = mask.mask[i, :], sup[i, :]
            a, b = j0, j1
        while a > 0 and col_m[a - 1] and not col_s[a]:
            a -= 1
        while b < len(col_m) - 1 and col_m[b + 1] and not col_s[b]:
            b += 1
        if vertical:
            seg = (pos, mask.y0 + a * mask.res, pos, mask.y0 + (b + 1) * mask.res)
        else:
            seg = (mask.x0 + a * mask.res, pos, mask.x0 + (b + 1) * mask.res, pos)
        if abs(seg[2] - seg[0]) + abs(seg[3] - seg[1]) < 1.0:
            break
        walls.append((*seg, "v"))
        added += 1
        bld = structure_from_walls(walls, max_span=max_span, footprint=fp, **kw)
    bld.slab = mask.to_dict()
    bld.walls = bld.walls[:n_real]
    if added:
        bld.warnings.append(f"{added} file(s) de poutres ajoutée(s) sans mur dessous (rives et plancher de "
                            f"portée > {slab_span:g} m) : à valider.")
    return bld
