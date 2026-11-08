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
                         res: float = 0.10, extra_columns: list[tuple[float, float]] = ()) -> Building:
    """`walls` : axes orthogonaux (x0, y0, x1, y1) en m ; `footprint` : rectangles (x0, y0, x1, y1)
    couverts par le plancher ou la toiture (sinon enveloppe des murs)."""
    W = []
    for x0, y0, x1, y1 in walls:
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
    for k, a, b, c in W:
        pts += [(a, c), (b, c)] if k == "H" else [(c, a), (c, b)]
    for i, (ka, a0, a1, ac) in enumerate(W):
        for kb, b0, b1, bc in W[i + 1:]:
            if ka == kb:
                continue
            h, v = ((a0, a1, ac), (b0, b1, bc)) if ka == "H" else ((b0, b1, bc), (a0, a1, ac))
            x, y = v[2], h[2]
            if h[0] - merge <= x <= h[1] + merge and v[0] - merge <= y <= v[1] + merge:
                pts.append((x, y))
    # 2) fusion des nœuds voisins
    nodes: list[list[float]] = []
    for x, y in pts:
        for n in nodes:
            if abs(n[0] - x) <= merge and abs(n[1] - y) <= merge:
                n[2].append((x, y))
                break
        else:
            nodes.append([x, y, [(x, y)]])
    nodes = [[float(np.mean([p[0] for p in n[2]])), float(np.mean([p[1] for p in n[2]]))] for n in nodes]

    for n in nodes:   # recalage exact sur les axes des murs porteurs du nœud
        hs = [w[3] for w in W if w[0] == "H" and abs(n[1] - w[3]) <= merge and w[1] - merge <= n[0] <= w[2] + merge]
        vs = [w[3] for w in W if w[0] == "V" and abs(n[0] - w[3]) <= merge and w[1] - merge <= n[1] <= w[2] + merge]
        if hs:
            n[1] = min(hs, key=lambda v: abs(v - n[1]))
        if vs:
            n[0] = min(vs, key=lambda v: abs(v - n[0]))

    def on_wall(n, w):
        k, a, b, c = w
        return (abs(n[1] - c) <= merge and a - merge <= n[0] <= b + merge) if k == "H" else \
            (abs(n[0] - c) <= merge and a - merge <= n[1] <= b + merge)

    # 3) poteaux intermédiaires sur les longues portées, alignés si possible sur les files existantes
    for w in W:
        k = w[0]
        along = sorted(((n[0] if k == "H" else n[1]), i) for i, n in enumerate(nodes) if on_wall(n, w))
        files = sorted({round(n[0] if k == "H" else n[1], 3) for n in nodes})
        for (pa, _), (pb, _) in zip(along, along[1:]):
            cur = pa
            while pb - cur > max_span:
                cands = [f for f in files if cur + 1.0 <= f <= min(cur + max_span, pb - 1.0)]
                if cands:
                    t = max(cands)
                else:
                    m = math.ceil((pb - cur) / max_span)
                    t = cur + (pb - cur) / m
                nodes.append([t, w[3]] if k == "H" else [w[3], t])
                cur = t
    # 4) poteaux et poutres
    order = sorted(range(len(nodes)), key=lambda i: (-round(nodes[i][1], 1), nodes[i][0]))
    ids = {i: f"P{n + 1}" for n, i in enumerate(order)}
    columns = [Column(ids[i], round(nodes[i][0], 3), round(nodes[i][1], 3), col[0], col[1]) for i in order]
    beams: list[Beam] = []
    seen = set()
    for w in W:
        k = w[0]
        along = sorted(((nodes[i][0] if k == "H" else nodes[i][1]), i) for i in range(len(nodes)) if on_wall(nodes[i], w))
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
