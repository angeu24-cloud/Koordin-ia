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
        source=drawing.source,
        warnings=list(drawing.warnings),
    )
