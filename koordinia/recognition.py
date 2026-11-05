"""Reconnaissance du système porteur (poteaux, poutres, panneaux) à partir d'un plan.

Stratégie :
1. Poteaux = petits rectangles sur un calque « poteau » ; à défaut, petits
   rectangles pleins (hachurés/remplis) ; à défaut, tous les petits rectangles.
2. Les centres des poteaux sont regroupés en files (axes) X et Y.
3. Les poutres relient deux poteaux consécutifs d'une même file.
4. Un panneau de plancher existe là où une maille de la trame a ses 4 poteaux.

Le résultat est une PROPOSITION : il doit être vérifié par l'ingénieur
(fichier modele.json éditable + plan de contrôle DXF).
"""
from __future__ import annotations

import math
import re

from .geometry import Drawing, Rect
from .model import Beam, Building, Column, Panel
from .slab import SlabMask, _dilate, mask_from_drawing

COLUMN_LAYER_RE = re.compile(r"POT|COLON|COLUMN|^COL|S-COLS|STRU.*COL", re.IGNORECASE)

MIN_COL = 0.15   # m
MAX_COL = 1.20   # m
MAX_ASPECT = 4.0


def _is_column_size(r: Rect) -> bool:
    w, h = r.width, r.height
    return MIN_COL - 1e-6 <= w <= MAX_COL and MIN_COL - 1e-6 <= h <= MAX_COL and max(w, h) / min(w, h) <= MAX_ASPECT


def _dedupe(rects: list[Rect], tol: float = 0.05) -> list[Rect]:
    kept: list[Rect] = []
    for r in sorted(rects, key=lambda r: -r.width * r.height):
        if any(abs(r.cx - k.cx) < tol + k.width / 2 and abs(r.cy - k.cy) < tol + k.height / 2 for k in kept):
            continue
        kept.append(r)
    return kept


def find_columns(drawing: Drawing, layer: str | None = None) -> tuple[list[Rect], str]:
    """Rectangles représentant les poteaux, et la méthode de détection employée.

    `layer` : nom (ou expression régulière) du calque des poteaux, s'il est connu.
    """
    candidates = [r for r in drawing.rects if _is_column_size(r)]
    if layer:
        rx = re.compile(f"^(?:{layer})$", re.IGNORECASE)
        forced = [r for r in candidates if rx.search(r.layer or "")]
        return _dedupe(forced), f"calque imposé « {layer} »"
    on_layer = [r for r in candidates if r.layer and COLUMN_LAYER_RE.search(r.layer)]
    if on_layer:
        return _dedupe(on_layer), "calque poteaux"
    filled = [r for r in candidates if r.filled]
    if len(filled) >= 4:
        # Les poteaux sont en général tous hachurés sur un même calque : on garde le calque dominant
        counts: dict[str, int] = {}
        for r in filled:
            counts[r.layer] = counts.get(r.layer, 0) + 1
        main, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= 0.7 * len(filled):
            return _dedupe([r for r in filled if r.layer == main]), f"hachures pleines du calque « {main} »"
        return _dedupe(filled), "rectangles pleins/hachurés"
    return _dedupe(candidates), "tous les petits rectangles (aucun calque poteau ni remplissage)"


def cluster(values: list[float], tol: float) -> list[float]:
    """Regroupe des coordonnées proches ; renvoie la moyenne de chaque groupe."""
    groups: list[list[float]] = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [float(sum(g) / len(g)) for g in groups]


def _nearest(grid: list[float], v: float) -> int:
    return min(range(len(grid)), key=lambda i: abs(grid[i] - v))


AXIS_LABEL_RE = re.compile(r"^[A-Z]{1,2}'?$|^\d{1,2}'?$")


def read_axis_labels(drawing: Drawing, grid_x, grid_y, ox, oy, rects) -> tuple[list[str], list[str]]:
    """Lit les repères d'axes de l'architecte (bulles en bout de files) ; vide si introuvables."""
    if not drawing.texts:
        return [], []
    x0, x1 = min(r.x0 for r in rects), max(r.x1 for r in rects)
    y0, y1 = min(r.y0 for r in rects), max(r.y1 for r in rects)
    labels = [t for t in drawing.texts if AXIS_LABEL_RE.match(t.text.strip().upper())]

    def pick(coord: float, along_x: bool) -> str | None:
        votes: dict[str, int] = {}
        for t in labels:
            if along_x:
                ok = abs(t.x - coord) < 0.35 and (t.y > y1 + 0.5 or t.y < y0 - 0.5) and abs(t.y - (y0 + y1) / 2) < 30
            else:
                ok = abs(t.y - coord) < 0.35 and (t.x > x1 + 0.5 or t.x < x0 - 0.5) and abs(t.x - (x0 + x1) / 2) < 40
            if ok:
                key = t.text.strip().upper()
                votes[key] = votes.get(key, 0) + 1
        return max(votes, key=votes.get) if votes else None

    ax = [pick(g + ox, True) for g in grid_x]
    ay = [pick(g + oy, False) for g in grid_y]
    if sum(a is not None for a in ax) < 0.5 * len(ax) or sum(a is not None for a in ay) < 0.5 * len(ay):
        return [], []
    def fill(names: list[str | None]) -> list[str]:
        out: list[str] = []
        for k, n in enumerate(names):
            out.append(n if n else (out[-1] + "+" if out else "0"))
        return out

    return fill(ax), fill(ay)


def default_beam_height(span: float) -> float:
    """Pré-dimensionnement h ≈ L/12, arrondi aux 5 cm supérieurs, minimum 30 cm."""
    return max(0.30, math.ceil(span / 12 / 0.05 - 1e-9) * 0.05)


def build_model(
    drawing: Drawing,
    *,
    n_levels: int = 1,
    floor_height: float = 3.0,
    grid_tol: float = 0.30,
    max_span: float = 8.0,
    beam_width: float | None = None,
    column_layer: str | None = None,
    footprint: bool = True,
) -> Building:
    rects, method = find_columns(drawing, layer=column_layer)
    bld = Building(n_levels=n_levels, floor_height=floor_height, source=drawing.source)
    bld.warnings.extend(drawing.warnings)
    bld.warnings.append(f"Poteaux détectés par : {method} ({len(rects)} trouvés).")
    if len(rects) < 4:
        bld.warnings.append(
            "Moins de 4 poteaux détectés : vérifiez le calque des poteaux, l'échelle ou les unités du plan."
        )
        return bld

    # Origine ramenée au coin bas-gauche de la trame
    ox = min(r.cx for r in rects)
    oy = min(r.cy for r in rects)
    bld.origin = [round(ox, 4), round(oy, 4)]

    # Contour du plancher déduit des murs (plans d'architecte)
    mask = None
    if footprint:
        m = 4.0
        bbox = (min(r.x0 for r in rects) - m, min(r.y0 for r in rects) - m,
                max(r.x1 for r in rects) + m, max(r.y1 for r in rects) + m)
        mask = mask_from_drawing(drawing, bbox, keep_layers={r.layer for r in rects if r.layer})
        if mask is not None:
            mask.x0 -= ox
            mask.y0 -= oy
            bld.slab = mask.to_dict()
            bld.warnings.append(f"Contour de plancher déduit des murs : {mask.area:.1f} m² (à vérifier).")
        else:
            bld.warnings.append("Contour de plancher non détecté : on utilise les mailles complètes de la trame.")
    bld.grid_x = [round(v - ox, 3) for v in cluster([r.cx for r in rects], grid_tol)]
    bld.grid_y = [round(v - oy, 3) for v in cluster([r.cy for r in rects], grid_tol)]

    bld.axis_x, bld.axis_y = read_axis_labels(drawing, bld.grid_x, bld.grid_y, ox, oy, rects)

    nodes: dict[tuple[int, int], Column] = {}
    for r in sorted(rects, key=lambda r: (round(r.cy - oy, 1), r.cx)):
        i, j = _nearest(bld.grid_x, r.cx - ox), _nearest(bld.grid_y, r.cy - oy)
        if (i, j) in nodes:
            bld.warnings.append(f"Deux poteaux sur le même nœud de trame ({i},{j}) : un seul conservé.")
            continue
        col = Column(
            id="", x=round(r.cx - ox, 3), y=round(r.cy - oy, 3),
            b=round(r.width, 3), h=round(r.height, 3), grid_i=i, grid_j=j,
        )
        nodes[(i, j)] = col
    # Numérotation P1, P2… ligne par ligne (de bas en haut, gauche à droite)
    for n, key in enumerate(sorted(nodes, key=lambda k: (k[1], k[0])), start=1):
        nodes[key].id = f"P{n}"
    bld.columns = [nodes[k] for k in sorted(nodes, key=lambda k: (k[1], k[0]))]

    # Poutres le long des files
    beams: dict[tuple[tuple[int, int], tuple[int, int]], Beam] = {}
    nb = 0

    def add_beam(a: Column, c: Column, direction: str) -> None:
        nonlocal nb
        span = math.hypot(a.x - c.x, a.y - c.y)
        if span > max_span:
            bld.warnings.append(
                f"Portée {a.id}–{c.id} = {span:.2f} m > {max_span} m : poutre non créée (vérifier)."
            )
            return
        nb += 1
        width = beam_width or max(0.20, min(a.b if direction == "Y" else a.h, 0.40))
        beams[((a.grid_i, a.grid_j), (c.grid_i, c.grid_j))] = Beam(
            id=f"N{nb}", start=a.id, end=c.id, b=round(width, 2), h=default_beam_height(span), direction=direction,
        )

    for j in range(len(bld.grid_y)):
        row = sorted([c for c in bld.columns if c.grid_j == j], key=lambda c: c.grid_i)
        for a, c in zip(row, row[1:]):
            add_beam(a, c, "X")
    for i in range(len(bld.grid_x)):
        col_line = sorted([c for c in bld.columns if c.grid_i == i], key=lambda c: c.grid_j)
        for a, c in zip(col_line, col_line[1:]):
            add_beam(a, c, "Y")
    if mask is not None:
        dil = SlabMask(mask.res, mask.x0, mask.y0, _dilate(mask.mask, int(0.5 / mask.res)))
        ny, nx = dil.mask.shape
        for key, bm in list(beams.items()):
            c1, c2 = nodes[key[0]], nodes[key[1]]
            pts = [(c1.x + t * (c2.x - c1.x), c1.y + t * (c2.y - c1.y)) for t in (0.25, 0.5, 0.75)]
            ok = all(0 <= int((x - dil.x0) / dil.res) < nx and 0 <= int((y - dil.y0) / dil.res) < ny
                     and dil.mask[int((y - dil.y0) / dil.res), int((x - dil.x0) / dil.res)] for x, y in pts)
            if not ok:
                del beams[key]
    bld.beams = list(beams.values())
    for n, b in enumerate(bld.beams, start=1):
        b.id = f"N{n}"

    # Panneaux de plancher
    np_ = 0
    for i in range(len(bld.grid_x) - 1):
        for j in range(len(bld.grid_y) - 1):
            corners = [(i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)]
            if not all(k in nodes for k in corners):
                continue
            sides = [
                beams.get(((i, j), (i + 1, j))),          # bas
                beams.get(((i, j + 1), (i + 1, j + 1))),  # haut
                beams.get(((i, j), (i, j + 1))),          # gauche
                beams.get(((i + 1, j), (i + 1, j + 1))),  # droite
            ]
            if any(s is None for s in sides):
                continue
            np_ += 1
            bld.panels.append(Panel(
                id=f"D{np_}",
                beams=[s.id for s in sides],
                lx=round(bld.grid_x[i + 1] - bld.grid_x[i], 3),
                ly=round(bld.grid_y[j + 1] - bld.grid_y[j], 3),
                corners=[nodes[k].id for k in corners],
            ))
    bld.warnings.append(
        f"Modèle proposé : {len(bld.columns)} poteaux, {len(bld.beams)} poutres, {len(bld.panels)} panneaux. "
        "À VÉRIFIER par l'ingénieur avant exploitation."
    )
    return bld
