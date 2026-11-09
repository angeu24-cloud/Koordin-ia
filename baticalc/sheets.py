"""Détection des planches (cadres) d'un dessin regroupant plusieurs plans.

Les architectes placent souvent tous les plans (RDC, étages, façades, coupes) côte
à côte dans le même DWG, chacun dans un cadre avec un cartouche. On repère ces
cadres, on lit leur titre et on permet de n'en traiter qu'un.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .geometry import Drawing, Rect

TITLE_RE = re.compile(r"PLAN|NIVEAU|ETAGE|R\.?D\.?C|REZ|SOUS.?SOL|TERRASSE|TOITURE|FACADE|COUPE|MASSE|FONDATION",
                      re.IGNORECASE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


@dataclass
class Sheet:
    index: int
    bbox: tuple[float, float, float, float]
    title: str

    @property
    def is_plan(self) -> bool:
        t = _norm(self.title)
        return "PLAN" in t and not any(k in t for k in ("MASSE", "FACADE", "COUPE", "SITUATION"))


def find_sheets(drawing: Drawing, min_size: float = 8.0) -> list[Sheet]:
    """Planches = cadres de plus haut niveau, en ignorant les cadres « généraux » qui
    regroupent plusieurs planches (leurs sous-cadres couvrent l'essentiel de leur surface)."""
    big = [r for r in drawing.rects if r.width >= min_size and r.height >= min_size * 0.6]
    big.sort(key=lambda r: -(r.width * r.height))

    def area(r: Rect) -> float:
        return r.width * r.height

    def contains(a: Rect, b: Rect, tol: float = 0.01) -> bool:
        return a.x0 - tol <= b.x0 and a.y0 - tol <= b.y0 and b.x1 <= a.x1 + tol and b.y1 <= a.y1 + tol

    frames: list[Rect] = []
    if not big:
        return sheets_from_titles(drawing)
    for r in big:
        # cadre double/triple : on garde le plus extérieur
        if any(contains(f, r) and area(f) < 1.3 * area(r) for f in frames):
            continue
        frames.append(r)

    # arbre d'imbrication : parent = plus petit cadre contenant
    parent: dict[int, int | None] = {}
    for i, r in enumerate(frames):
        owners = [j for j, f in enumerate(frames) if j != i and contains(f, r) and area(f) > area(r)]
        parent[i] = min(owners, key=lambda j: area(frames[j])) if owners else None
    children: dict[int | None, list[int]] = {}
    for i, p in parent.items():
        children.setdefault(p, []).append(i)

    def is_group(i: int) -> bool:
        kids = children.get(i, [])
        return len(kids) >= 2 and sum(area(frames[k]) for k in kids) >= 0.3 * area(frames[i])

    chosen: list[Rect] = []
    stack = list(children.get(None, []))
    while stack:
        i = stack.pop()
        if is_group(i):
            stack.extend(children.get(i, []))
        else:
            chosen.append(frames[i])
    frames = sorted(chosen, key=lambda f: (round(-f.cy / 10), f.cx))

    sheets: list[Sheet] = []
    for k, f in enumerate(frames, start=1):
        texts = [t for t in drawing.texts if f.x0 <= t.x <= f.x1 and f.y0 <= t.y <= f.y1]
        cands = [t.text for t in texts if TITLE_RE.search(_norm(t.text)) and len(t.text) < 80]
        # on privilégie « VUE EN PLAN … » / « PLAN … »
        def rank(txt: str) -> tuple[int, int]:
            t = _norm(txt)
            if t.startswith(("VUE EN PLAN", "PLAN")):
                return 0, len(t)
            if re.search(r"FACADES?|COUPES?|MASSE|FONDATION", t):
                return 1, len(t)
            return 2, -len(t)
        cands.sort(key=rank)
        title = re.sub(r"\s+", " ", cands[0]).strip() if cands else f"Planche {k}"
        sheets.append(Sheet(k, (f.x0, f.y0, f.x1, f.y1), title))
    return sheets


HEADING_RE = re.compile(r"^(VUE EN )?PLAN\b|^FACADES?\b|^COUPES?\b|^PLAN DE MASSE|^TOITURE|^FONDATION", re.IGNORECASE)


def sheets_from_titles(drawing: Drawing, gap: float = 3.0, max_cells: int = 1500) -> list[Sheet]:
    """Dessin sans cadres : groupes de traits séparés par plus de `gap` m de vide, chacun nommé par
    le titre (« PLAN COTE RDC », « FACADE PRINCIPALE »…) écrit sous lui ou dedans."""
    import numpy as np

    from .slab import _dilate

    segs = drawing.segments
    titles = [t for t in drawing.texts if HEADING_RE.search(_norm(t.text)) and len(t.text) < 60]
    if not segs or not titles:
        return []
    xs = np.array([v for sg in segs for v in (sg.x0, sg.x1)] + [v for r in drawing.rects for v in (r.x0, r.x1)])
    ys = np.array([v for sg in segs for v in (sg.y0, sg.y1)] + [v for r in drawing.rects for v in (r.y0, r.y1)])
    x0, y0 = float(np.percentile(xs, 0.5)) - gap, float(np.percentile(ys, 0.5)) - gap
    x1, y1 = float(np.percentile(xs, 99.5)) + gap, float(np.percentile(ys, 99.5)) + gap
    cell = max(gap / 4, (x1 - x0) / max_cells, (y1 - y0) / max_cells)
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    occ = np.zeros((ny, nx), dtype=bool)
    lines = [(sg.x0, sg.y0, sg.x1, sg.y1) for sg in segs] + \
        [ln for r in drawing.rects for ln in ((r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                                              (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0))]
    for a, b, c, d in lines:
        n = int(max(abs(c - a), abs(d - b)) / cell) + 2
        if n > 4 * max(nx, ny):
            continue                      # trait démesuré (ligne de construction)
        t = np.linspace(0, 1, n)
        i = ((b + t * (d - b) - y0) / cell).astype(int)
        j = ((a + t * (c - a) - x0) / cell).astype(int)
        ok = (i >= 0) & (i < ny) & (j >= 0) & (j < nx)
        occ[i[ok], j[ok]] = True
    grown = _dilate(occ, max(1, int(round(gap / 2 / cell))))
    from collections import deque

    lab = np.zeros(grown.shape, dtype=np.int32)
    boxes: list[list[float]] = []
    for si, sj in zip(*np.nonzero(grown)):
        if lab[si, sj]:
            continue
        k = len(boxes) + 1
        lab[si, sj] = k
        q = deque([(si, sj)])
        b = [sj, si, sj, si, 0]
        while q:
            i, j = q.popleft()
            b = [min(b[0], j), min(b[1], i), max(b[2], j), max(b[3], i), b[4] + int(occ[i, j])]
            for u, v in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= u < ny and 0 <= v < nx and grown[u, v] and not lab[u, v]:
                    lab[u, v] = k
                    q.append((u, v))
        boxes.append(b)
    groups = [(x0 + b[0] * cell, y0 + b[1] * cell, x0 + (b[2] + 1) * cell, y0 + (b[3] + 1) * cell, b[4])
              for b in boxes]
    groups = [g for g in groups if g[2] - g[0] >= 3 and g[3] - g[1] >= 3 and g[4] >= 20]
    found: dict[int, tuple[float, str]] = {}
    for t in titles:
        best = None
        for gi, (gx0, gy0, gx1, gy1, _) in enumerate(groups):
            if not (gx0 - gap <= t.x <= gx1 + gap):
                continue
            if gy0 <= t.y <= gy1:
                d = 0.5          # titre dans le groupe
            elif t.y < gy0:
                d = gy0 - t.y    # titre sous le dessin (usage courant)
            else:
                d = 2 * (t.y - gy1)
            if d <= 3 * gap + 0.05 * (gy1 - gy0) and (best is None or d < best[0]):
                best = (d, gi)
        if best and (best[1] not in found or best[0] < found[best[1]][0]):
            found[best[1]] = (best[0], re.sub(r"\s+", " ", t.text).strip())
    order = sorted(found, key=lambda gi: (round(-groups[gi][1] / 10), groups[gi][0]))
    return [Sheet(k, tuple(groups[gi][:4]), found[gi][1]) for k, gi in enumerate(order, start=1)]


def select_sheet(sheets: list[Sheet], query: str) -> Sheet:
    if query.isdigit():
        n = int(query)
        for s in sheets:
            if s.index == n:
                return s
        raise ValueError(f"Planche n° {n} inexistante (1 à {len(sheets)}).")
    q = _norm(query)
    words = q.split()
    matches = [s for s in sheets if all(w in _norm(s.title) for w in words)]
    if not matches:
        raise ValueError(
            f"Aucune planche ne correspond à « {query} ». Planches disponibles :\n"
            + "\n".join(f"  {s.index}. {s.title}" for s in sheets)
        )
    return matches[0]


def crop(drawing: Drawing, bbox: tuple[float, float, float, float]) -> Drawing:
    x0, y0, x1, y1 = bbox
    return Drawing(
        rects=[r for r in drawing.rects if x0 <= r.cx <= x1 and y0 <= r.cy <= y1
               and not (r.width > 0.9 * (x1 - x0))],
        segments=[s for s in drawing.segments
                  if x0 <= min(s.x0, s.x1) and max(s.x0, s.x1) <= x1 and y0 <= min(s.y0, s.y1)
                  and max(s.y0, s.y1) <= y1],
        texts=[t for t in drawing.texts if x0 <= t.x <= x1 and y0 <= t.y <= y1],
        marks=[m for m in drawing.marks if x0 <= (m.x0 + m.x1) / 2 <= x1 and y0 <= (m.y0 + m.y1) / 2 <= y1],
        source=drawing.source,
        warnings=list(drawing.warnings),
    )
