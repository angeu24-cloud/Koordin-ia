"""Contour de plancher représenté par une grille de cellules (raster).

- Pour un plan d'architecte réel, le contour est déduit des murs, menuiseries et
  garde-corps : on « remplit » depuis l'extérieur, ce qui n'est pas atteint est
  l'intérieur du bâtiment (balcons compris).
- Pour une trame régulière, c'est l'union des panneaux de plancher.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

import numpy as np

from .geometry import Drawing

# Calques qui ne délimitent pas le bâtiment
NON_BARRIER_RE = re.compile(
    r"COT|DIM|AXE|AXIS|GRID|TEXT|TXT|NIV|LEVL|VRD|VOITURE|AUTO|MOBIL|MEUBLE|EQUIP|SYMB|CADRE|CARREL|HACH|"
    r"NOMENC|DEFPOINTS|TOIT|ELEV|COUPE",
    re.IGNORECASE,
)


@dataclass
class SlabMask:
    res: float
    x0: float
    y0: float
    mask: np.ndarray  # booléen [ny, nx], True = plancher

    @property
    def area(self) -> float:
        return float(self.mask.sum()) * self.res ** 2

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        jj, ii = np.nonzero(self.mask)
        return self.x0 + (ii + 0.5) * self.res, self.y0 + (jj + 0.5) * self.res

    # ---------------------------------------------------------- sérialisation
    def to_dict(self) -> dict:
        runs = []
        for j, row in enumerate(self.mask):
            i = 0
            n = len(row)
            while i < n:
                if row[i]:
                    k = i
                    while k < n and row[k]:
                        k += 1
                    runs.append([j, i, k])
                    i = k
                else:
                    i += 1
        ny, nx = self.mask.shape
        return {"res": self.res, "x0": self.x0, "y0": self.y0, "nx": nx, "ny": ny, "runs": runs}

    @classmethod
    def from_dict(cls, d: dict) -> "SlabMask":
        m = np.zeros((d["ny"], d["nx"]), dtype=bool)
        for j, i0, i1 in d["runs"]:
            m[j, i0:i1] = True
        return cls(d["res"], d["x0"], d["y0"], m)


def mask_from_rects(rects: list[tuple[float, float, float, float]], res: float = 0.10) -> SlabMask:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    nx = max(1, round((x1 - x0) / res))
    ny = max(1, round((y1 - y0) / res))
    m = np.zeros((ny, nx), dtype=bool)
    for a, b, c, d in rects:
        i0, i1 = round((a - x0) / res), round((c - x0) / res)
        j0, j1 = round((b - y0) / res), round((d - y0) / res)
        m[j0:j1, i0:i1] = True
    return SlabMask(res, x0, y0, m)


def _dilate(m: np.ndarray, r: int, square: bool = False) -> np.ndarray:
    """Dilatation par un disque (ou un carré) de rayon r cellules."""
    ny, nx = m.shape
    out = m.copy()
    for dj in range(-r, r + 1):
        w = r if square else int((r * r - dj * dj) ** 0.5)
        for di in range(-w, w + 1):
            if dj == 0 and di == 0:
                continue
            ys, yd = (slice(0, ny - dj), slice(dj, ny)) if dj >= 0 else (slice(-dj, ny), slice(0, ny + dj))
            xs, xd = (slice(0, nx - di), slice(di, nx)) if di >= 0 else (slice(-di, nx), slice(0, nx + di))
            out[yd, xd] |= m[ys, xs]
    return out


def _components(m: np.ndarray, diag: bool = False):
    """Composantes connexes : liste de (lignes, colonnes)."""
    ny, nx = m.shape
    seen = np.zeros_like(m)
    nb = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diag:
        nb += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    for j0, i0 in zip(*np.nonzero(m)):
        if seen[j0, i0]:
            continue
        comp = [(j0, i0)]
        seen[j0, i0] = True
        k = 0
        while k < len(comp):
            j, i = comp[k]
            k += 1
            for dj, di in nb:
                a, b = j + dj, i + di
                if 0 <= a < ny and 0 <= b < nx and m[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    comp.append((a, b))
        js, is_ = zip(*comp)
        yield np.array(js), np.array(is_)


def mask_from_drawing(
    drawing: Drawing,
    bbox: tuple[float, float, float, float],
    *,
    res: float = 0.10,
    gap: float = 3.0,
    min_area: float = 4.0,
    keep_layers: set[str] | None = None,
) -> SlabMask | None:
    """Intérieur du bâtiment dans `bbox` (coordonnées du dessin, m).

    `gap` : largeur maximale d'une ouverture non dessinée qui sera refermée.
    `keep_layers` : calques toujours considérés comme structurels (ex. calque des poteaux).
    """
    x0, y0, x1, y1 = bbox
    nx, ny = int((x1 - x0) / res) + 1, int((y1 - y0) / res) + 1
    wall = np.zeros((ny, nx), dtype=bool)

    def mark_segment(ax, ay, bx, by):
        n = int(max(abs(bx - ax), abs(by - ay)) / (res / 2)) + 2
        xs = np.linspace(ax, bx, n)
        ys = np.linspace(ay, by, n)
        ii = ((xs - x0) / res).astype(int)
        jj = ((ys - y0) / res).astype(int)
        ok = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
        wall[jj[ok], ii[ok]] = True

    keep = {k.upper() for k in (keep_layers or set())}

    def excluded(layer: str) -> bool:
        return bool(layer) and layer.upper() not in keep and bool(NON_BARRIER_RE.search(layer))

    for s in drawing.segments:
        if s.dashed or excluded(s.layer):
            continue
        mark_segment(s.x0, s.y0, s.x1, s.y1)
    for r in drawing.rects:
        if excluded(r.layer):
            continue
        for a, b, c, d in ((r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                           (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)):
            mark_segment(a, b, c, d)
    if wall.sum() == 0:
        return None
    # Petits traits isolés (repères d'axes, symboles) : ignorés
    min_len = int(1.5 / res)
    for js, is_ in list(_components(wall, diag=True)):
        if js.max() - js.min() < min_len and is_.max() - is_.min() < min_len:
            wall[js, is_] = False
    # 1) Test des 4 directions : un mur à gauche, à droite, en haut et en bas
    right = np.maximum.accumulate(wall[:, ::-1], axis=1)[:, ::-1]
    left = np.maximum.accumulate(wall, axis=1)
    up = np.maximum.accumulate(wall[::-1, :], axis=0)[::-1, :]
    down = np.maximum.accumulate(wall, axis=0)
    enclosed = left & right & up & down

    # 2) Remplissage depuis l'extérieur, ouvertures ≤ gap refermées
    rad = max(1, int(round(gap / 2 / res)))
    barrier = _dilate(wall, rad)
    outside = np.zeros_like(barrier)
    q: deque[tuple[int, int]] = deque()
    border = [(j, i) for i in range(nx) for j in (0, ny - 1)] + [(j, i) for j in range(ny) for i in (0, nx - 1)]
    for j, i in border:
        if not barrier[j, i] and not outside[j, i]:
            outside[j, i] = True
            q.append((j, i))
    while q:
        j, i = q.popleft()
        for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = j + dj, i + di
            if 0 <= a < ny and 0 <= b < nx and not outside[a, b] and not barrier[a, b]:
                outside[a, b] = True
                q.append((a, b))
    filled = ~_dilate(outside, rad, square=True)

    # Union des deux critères, puis lissage (fermeture 30 cm)
    inside = enclosed | filled
    r2 = max(1, int(round(0.3 / res)))
    inside = ~_dilate(~_dilate(inside, r2, square=True), r2, square=True)
    inside = _drop_small_components(inside, int(min_area / res ** 2))
    if not inside.any():
        return None
    return SlabMask(res, x0, y0, inside)


def _drop_small_components(m: np.ndarray, min_cells: int) -> np.ndarray:
    out = np.zeros_like(m)
    for js, is_ in _components(m):
        if len(js) >= min_cells:
            out[js, is_] = True
    return out


def outline_segments(m: SlabMask) -> list[tuple[float, float, float, float]]:
    """Contour du plancher : segments horizontaux/verticaux fusionnés."""
    a = m.mask
    ny, nx = a.shape
    pad = np.zeros((ny + 2, nx + 2), dtype=bool)
    pad[1:-1, 1:-1] = a
    segs: list[tuple[float, float, float, float]] = []
    # arêtes horizontales : entre lignes j-1 et j
    h = pad[1:, 1:-1] != pad[:-1, 1:-1]          # (ny+1, nx)
    for j in range(ny + 1):
        row = h[j]
        i = 0
        while i < nx:
            if row[i]:
                k = i
                while k < nx and row[k]:
                    k += 1
                y = m.y0 + j * m.res
                segs.append((m.x0 + i * m.res, y, m.x0 + k * m.res, y))
                i = k
            else:
                i += 1
    v = pad[1:-1, 1:] != pad[1:-1, :-1]          # (ny, nx+1)
    for i in range(nx + 1):
        col = v[:, i]
        j = 0
        while j < ny:
            if col[j]:
                k = j
                while k < ny and col[k]:
                    k += 1
                x = m.x0 + i * m.res
                segs.append((x, m.y0 + j * m.res, x, m.y0 + k * m.res))
                j = k
            else:
                j += 1
    return segs
