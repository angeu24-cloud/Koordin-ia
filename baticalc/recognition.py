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
    origin: tuple[float, float] | None = None,
    rooms: bool = True,
    usages: list[dict] | None = None,
    propose: bool | None = None,
    column_span: float = 4.5,
) -> Building:
    """Modèle d'un plan : poteaux, contour du plancher, murs, files, poutres.

    `origin` : origine imposée (coordonnées du dessin, m) pour caler plusieurs planches
    dans un même repère ; par défaut, coin bas-gauche de la trame des poteaux.
    `propose` : True = ossature proposée d'après les murs (poteaux ignorés), None = seulement
    si le plan ne dessine pas de poteaux ; `column_span` : écartement maximal des poteaux proposés.
    """
    rects, method = find_columns(drawing, layer=column_layer)
    bld = Building(n_levels=n_levels, floor_height=floor_height, source=drawing.source)
    bld.warnings.extend(drawing.warnings)
    bld.warnings.append(f"Poteaux détectés par : {method} ({len(rects)} trouvés).")
    if propose is None:
        propose = len(rects) < 4
    if propose:
        rects = []
        if not drawing.segments and not drawing.rects:
            bld.warnings.append("Plan vide : aucun trait exploitable.")
            return bld
    elif len(rects) < 4:
        bld.warnings.append(
            "Moins de 4 poteaux détectés : vérifiez le calque des poteaux, l'échelle ou les unités du plan."
        )
        return bld

    keep = {r.layer for r in rects if r.layer}
    m = 4.0
    if propose:     # plan d'architecte sans poteaux : emprise des traits pleins
        segs = [sg for sg in drawing.segments if not sg.dashed] or drawing.segments
        xs = [v for sg in segs for v in (sg.x0, sg.x1)] + [v for r in drawing.rects for v in (r.x0, r.x1)]
        ys = [v for sg in segs for v in (sg.y0, sg.y1)] + [v for r in drawing.rects for v in (r.y0, r.y1)]
        bbox = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
        raw = detect_walls(drawing, bbox, 0.0, 0.0, set(), min_len=0.25)
        if origin is not None:
            ox, oy = origin
        elif raw:
            ox, oy = min(min(w[0], w[2]) for w in raw), min(min(w[1], w[3]) for w in raw)
        else:
            ox, oy = bbox[0] + 1, bbox[1] + 1
    else:
        ox, oy = origin if origin is not None else (min(r.cx for r in rects), min(r.cy for r in rects))
        bbox = (min(r.x0 for r in rects) - m, min(r.y0 for r in rects) - m,
                max(r.x1 for r in rects) + m, max(r.y1 for r in rects) + m)
    bld.origin = [round(ox, 4), round(oy, 4)]
    if not propose and getattr(drawing, "scan", None) and drawing.segments:   # plan scanné : poteaux rarement dessinés
        xs = [v for sg in drawing.segments for v in (sg.x0, sg.x1)]
        ys = [v for sg in drawing.segments for v in (sg.y0, sg.y1)]
        bbox = (min(bbox[0], min(xs) - 1), min(bbox[1], min(ys) - 1), max(bbox[2], max(xs) + 1), max(bbox[3], max(ys) + 1))

    # Contour du plancher déduit des murs (plans d'architecte)
    mask = None
    if footprint:
        mask = mask_from_drawing(drawing, bbox, keep_layers=keep)
        if mask is not None:
            mask.x0 -= ox
            mask.y0 -= oy
            if propose:
                mask = main_component(mask, walls=[[w[0] - ox, w[1] - oy, w[2] - ox, w[3] - oy] for w in raw])
            bld.slab = mask.to_dict()
            bld.warnings.append(f"Contour de plancher déduit des murs : {mask.area:.1f} m² (à vérifier).")
        else:
            bld.warnings.append("Contour de plancher non détecté : on utilise les mailles complètes de la trame.")
    bld.walls = detect_walls(drawing, bbox, ox, oy, keep, min_len=0.25 if propose else 1.0)
    mask0 = mask       # plancher hors balcons (rives des poutres proposées)

    # Locaux étiquetés : usages, trémies, balcons, terrasses (sur la grille du contour)
    if rooms and mask is not None:
        from .zones import detect_zones, load_catalogue

        zones, notes = detect_zones(drawing, mask, ox, oy, load_catalogue(usages), keep_layers=keep,
                                    door=1.25 if getattr(drawing, "scan", None) else 0.95,
                                    unlabeled=bool(getattr(drawing, "scan", None)))
        bld.zones = zones
        bld.warnings += notes
        if zones:
            counts: dict[str, int] = {}
            for z in zones:
                counts[z["usage"]] = counts.get(z["usage"], 0) + 1
            bld.warnings.append("Locaux reconnus : " + ", ".join(f"{n} × {u}" for u, n in counts.items()) + ".")
            # balcons et terrasses hors du contour détecté : ajoutés au plancher
            ext = [z for z in zones if z["type"] in ("balcon",)]
            if ext:
                m2 = mask.mask.copy()
                for z in ext:
                    m2 |= SlabMask.from_dict(z["cells"]).mask
                if m2.sum() > mask.mask.sum():
                    mask = SlabMask(mask.res, mask.x0, mask.y0, m2)
                    bld.slab = mask.to_dict()

    if propose:
        _propose_frame(bld, mask, column_span=min(column_span, max_span), beam_width=beam_width, perimeter=mask0,
                       axes=axis_lines(drawing, bbox, ox, oy))
        outside = None
        if mask is not None:
            outside = ~mask.mask
            for z in bld.zones:
                if z["type"] in ("balcon", "exterieur"):
                    zm = SlabMask.from_dict(z["cells"])
                    if zm.mask.shape == outside.shape:
                        outside |= zm.mask
        bld.openings = detect_openings(drawing, bbox, ox, oy, mask, outside)
        if bld.zones:
            from .mep.fixtures import detect_fixtures

            bld.fixtures = detect_fixtures(drawing, bld.zones, ox, oy)
        return bld

    bld.columns = []
    for r in sorted(rects, key=lambda r: (round(r.cy - oy, 1), r.cx)):
        bld.columns.append(Column(id="", x=round(r.cx - ox, 3), y=round(r.cy - oy, 3),
                                  b=round(r.width, 3), h=round(r.height, 3)))
    outside = None
    if mask is not None:  # extérieur = hors plancher, balcons et terrasses compris
        outside = ~mask.mask
        for z in bld.zones:
            if z["type"] in ("balcon", "exterieur"):
                zm = SlabMask.from_dict(z["cells"])
                if zm.mask.shape == outside.shape:
                    outside |= zm.mask
    bld.openings = detect_openings(drawing, bbox, ox, oy, mask, outside)
    if bld.zones:
        from .mep.fixtures import detect_fixtures

        bld.fixtures = detect_fixtures(drawing, bld.zones, ox, oy)
    build_frame(bld, mask, grid_tol=grid_tol, max_span=max_span, beam_width=beam_width, renumber=True)
    bld.axis_x, bld.axis_y = read_axis_labels(drawing, bld.grid_x, bld.grid_y, ox, oy, rects)
    bld.warnings.append(
        f"Modèle proposé : {len(bld.columns)} poteaux, {len(bld.beams)} poutres, {len(bld.panels)} panneaux. "
        "À VÉRIFIER par l'ingénieur avant exploitation."
    )
    return bld


AXIS_LAYER_RE = re.compile(r"AXE|AXIS|GRID|TRAME|FILE", re.IGNORECASE)


def axis_lines(drawing: Drawing, bbox, ox: float, oy: float) -> tuple[list[float], list[float]]:
    """Axes du plan (files de l'architecte) : longs traits orthogonaux en tirets ou sur un calque d'axes."""
    x0b, y0b, x1b, y1b = bbox
    min_len = max(6.0, 0.35 * min(x1b - x0b, y1b - y0b))
    xs, ys = [], []
    for sg in drawing.segments:
        if not (sg.dashed or AXIS_LAYER_RE.search(sg.layer or "")):
            continue
        dx, dy = abs(sg.x1 - sg.x0), abs(sg.y1 - sg.y0)
        if dx <= 0.02 and dy >= min_len and x0b <= sg.x0 <= x1b:
            xs.append(sg.x0 - ox)
        elif dy <= 0.02 and dx >= min_len and y0b <= sg.y0 <= y1b:
            ys.append(sg.y0 - oy)
    return ([round(v, 3) for v in cluster(xs, 0.15)] if len(xs) >= 2 else [],
            [round(v, 3) for v in cluster(ys, 0.15)] if len(ys) >= 2 else [])


def main_component(mask: SlabMask, near: float = 3.0, walls=()) -> SlabMask:
    """Bâtiment principal : zone du plancher qui porte le plus de murs (`walls`, sinon la plus grande)
    et zones à moins de `near` m (écarte cartouches, légendes et détails dessinés à côté du plan)."""
    from collections import deque

    import numpy as np

    a = mask.mask
    lab = np.zeros(a.shape, dtype=np.int32)
    boxes = []
    for i0, j0 in zip(*np.nonzero(a)):
        if lab[i0, j0]:
            continue
        k = len(boxes) + 1
        lab[i0, j0] = k
        q = deque([(i0, j0)])
        n, b = 0, [i0, j0, i0, j0]
        while q:
            i, j = q.popleft()
            n += 1
            b = [min(b[0], i), min(b[1], j), max(b[2], i), max(b[3], j)]
            for u, v in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= u < a.shape[0] and 0 <= v < a.shape[1] and a[u, v] and not lab[u, v]:
                    lab[u, v] = k
                    q.append((u, v))
        boxes.append((n, b))
    if len(boxes) <= 1:
        return mask
    score = [float(n) for n, _ in boxes]
    if walls:
        score = [0.0] * len(boxes)
        ny, nx = a.shape
        for w in walls:
            L = abs(w[2] - w[0]) + abs(w[3] - w[1])
            for t in (0.25, 0.5, 0.75):
                x, y = w[0] + t * (w[2] - w[0]), w[1] + t * (w[3] - w[1])
                for dx, dy in ((0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2)):
                    i, j = int((y + dy - mask.y0) / mask.res), int((x + dx - mask.x0) / mask.res)
                    if 0 <= i < ny and 0 <= j < nx and lab[i, j]:
                        score[lab[i, j] - 1] += L / 3
                        break
    big = max(range(len(boxes)), key=lambda k: (score[k], boxes[k][0]))
    B = boxes[big][1]
    g = near / mask.res
    keep = [k + 1 for k, (n, b) in enumerate(boxes)
            if k == big or (b[0] <= B[2] + g and b[2] >= B[0] - g and b[1] <= B[3] + g and b[3] >= B[1] - g)]
    return SlabMask(mask.res, mask.x0, mask.y0, np.isin(lab, keep))


def structural_walls(walls: list[list[float]], mask: SlabMask | None, *, gap: float = 1.6,
                     min_len: float = 1.2) -> tuple[list[list[float]], list[tuple[float, float, float, float]]]:
    """Murs porteurs probables : axes regroupés (même file à 30 cm près), tronçons d'un même mur
    séparés par une baie (≤ `gap`) raccordés, cloisons minces et murs hors plancher écartés.

    Renvoie (murs [x0, y0, x1, y1, ép.], baies [x0, y0, x1, y1] sur les axes des murs)."""
    if not walls:
        return [], []
    thick = [w for w in walls if w[4] >= 0.12]
    tot = sum(math.hypot(w[2] - w[0], w[3] - w[1]) for w in walls)
    if sum(math.hypot(w[2] - w[0], w[3] - w[1]) for w in thick) >= 0.4 * tot:
        walls = thick          # cloisons de 5 à 10 cm : non porteuses
    inside = None
    if mask is not None:
        dil = SlabMask(mask.res, mask.x0, mask.y0, _dilate(mask.mask, int(0.6 / mask.res)))
        ny, nx = dil.mask.shape

        def inside(x, y):
            i, j = int((y - dil.y0) / dil.res), int((x - dil.x0) / dil.res)
            return 0 <= i < ny and 0 <= j < nx and bool(dil.mask[i, j])
    out, gaps = [], []
    for horiz in (True, False):
        items = []
        for w in walls:
            h = abs(w[2] - w[0]) >= abs(w[3] - w[1])
            if h != horiz:
                continue
            c = (w[1] + w[3]) / 2 if horiz else (w[0] + w[2]) / 2
            a, b = (min(w[0], w[2]), max(w[0], w[2])) if horiz else (min(w[1], w[3]), max(w[1], w[3]))
            items.append((c, a, b, w[4]))
        items.sort()
        files: list[list[tuple]] = []
        for it in items:
            if files and it[0] - files[-1][-1][0] <= 0.30:
                files[-1].append(it)
            else:
                files.append([it])
        for f in files:
            c = sum(i[0] * (i[2] - i[1]) for i in f) / max(1e-9, sum(i[2] - i[1] for i in f))
            t = max(i[3] for i in f)
            runs: list[list[float]] = []
            for _, a, b, _ in sorted(f, key=lambda i: i[1]):
                if runs and a <= runs[-1][1] + gap:
                    if a > runs[-1][1] + 0.3:
                        gaps.append((runs[-1][1], a, c, horiz))
                    runs[-1][1] = max(runs[-1][1], b)
                else:
                    runs.append([a, b])
            for a, b in runs:
                if b - a < min_len:
                    continue
                if inside is not None:
                    pts = [(a + (b - a) * k / 4, c) if horiz else (c, a + (b - a) * k / 4) for k in (1, 2, 3)]
                    if sum(inside(*p) for p in pts) < 2:
                        continue
                out.append([a, c, b, c, t] if horiz else [c, a, c, b, t])
    gap_segs = [(a, c, b, c) if h else (c, a, c, b) for a, b, c, h in gaps]
    return [[round(v, 3) for v in w] for w in out], gap_segs


def _propose_frame(bld: Building, mask: SlabMask | None, *, column_span: float = 4.5,
                   beam_width: float | None = None, perimeter: SlabMask | None = None,
                   axes: tuple[list[float], list[float]] = ([], [])) -> None:
    """Poteaux et poutres proposés d'après les murs (plan sans poteaux dessinés)."""
    walls, gaps = structural_walls(bld.walls, mask)
    if len(walls) < 3:
        bld.warnings.append("Pas assez de murs reconnus pour proposer une ossature : placez les poteaux "
                            "dans l'onglet « Structure ».")
        return
    rects = None
    if mask is None:
        rects = [(min(min(w[0], w[2]) for w in walls), min(min(w[1], w[3]) for w in walls),
                  max(max(w[0], w[2]) for w in walls), max(max(w[1], w[3]) for w in walls))]
    opts = dict(merge=0.40, col=(0.20, 0.20), beam=(beam_width or 0.20, 0.30), avoid=gaps, axes=axes)
    bld._prop = dict(walls=walls, mask=mask, perimeter=perimeter, span=column_span, rects=rects, opts=opts)
    _apply_proposal(bld)
    bld.warnings.append(
        f"Aucun poteau dessiné : ossature PROPOSÉE d'après les murs — {len(bld.columns)} poteaux 20×20, "
        f"{len(bld.beams)} poutres, écartement ≤ {column_span:g} m (angles, croisements, extrémités de murs, "
        "baies évitées). Corrigez-la dans l'onglet « Structure » avant le calcul."
    )


def _apply_proposal(bld: Building, *, extra_columns=(), carried: SlabMask | None = None,
                    upper_walls=()) -> None:
    """(Re)calcule l'ossature proposée de `bld` (contexte enregistré par `_propose_frame`).

    `extra_columns` : poteaux imposés (continuité avec l'étage supérieur) ; `carried` : plancher porté
    (celui de l'étage supérieur) ; `upper_walls` : murs de l'étage supérieur à reprendre par des poutres."""
    from .ossature import beams_on_walls, structure_from_walls, structure_on_slab

    ctx = bld._prop
    walls, mask, span, opts = ctx["walls"], ctx["mask"], ctx["span"], dict(ctx["opts"])
    slab = carried or mask
    if slab is not None:
        prop = structure_on_slab([tuple(w[:4]) for w in walls], slab,
                                 perimeter=ctx["perimeter"] if carried is None else carried,
                                 max_span=span, slab_span=span + 1.0, extra_columns=list(extra_columns),
                                 virtual_walls=[tuple(w[:4]) for w in upper_walls], **opts)
        upper_walls = ()
    else:
        prop = structure_from_walls([tuple(w[:4]) for w in walls], max_span=span, footprint=ctx["rects"],
                                    extra_columns=list(extra_columns), **opts)
    if upper_walls:   # poutres sous les murs de l'étage supérieur, entre poteaux de cet étage
        have = {tuple(sorted((b.start, b.end))) for b in prop.beams}
        more = beams_on_walls(prop.columns, upper_walls, beam=opts["beam"], start=len(prop.beams) + 1)
        prop.beams += [b for b in more if tuple(sorted((b.start, b.end))) not in have]
    cols = prop.column_map()
    for b in prop.beams:
        c1, c2 = cols[b.start], cols[b.end]
        b.h = default_beam_height(math.hypot(c2.x - c1.x, c2.y - c1.y))
    bld.columns, bld.beams, bld.panels = prop.columns, prop.beams, []
    bld.grid_x, bld.grid_y = prop.grid_x, prop.grid_y
    bld.walls = [w + [t] for w, t in zip([list(x[:4]) for x in prop.walls], [w[4] for w in walls])] \
        if len(prop.walls) == len(walls) else prop.walls
    if mask is None and carried is None:
        bld.slab = prop.slab
    bld.warnings = [w for w in bld.warnings if "file(s) de poutres" not in w] + \
        [w for w in prop.warnings if "file(s) de poutres" in w]
    bld.proposed = True


def build_frame(
    bld: Building,
    mask: SlabMask | None,
    *,
    grid_tol: float = 0.30,
    max_span: float = 8.0,
    beam_width: float | None = None,
    renumber: bool = False,
) -> None:
    """(Re)construit files, poutres et panneaux à partir des poteaux de `bld` et du contour `mask`."""
    bld.grid_x = [round(v, 3) for v in cluster([c.x for c in bld.columns], grid_tol)] if bld.columns else []
    bld.grid_y = [round(v, 3) for v in cluster([c.y for c in bld.columns], grid_tol)] if bld.columns else []
    bld.beams, bld.panels = [], []
    nodes: dict[tuple[int, int], Column] = {}
    kept: list[Column] = []
    for c in sorted(bld.columns, key=lambda c: (round(c.y, 1), c.x)):
        c.grid_i, c.grid_j = _nearest(bld.grid_x, c.x), _nearest(bld.grid_y, c.y)
        if (c.grid_i, c.grid_j) in nodes:
            bld.warnings.append(
                f"Deux poteaux sur le même nœud de trame ({c.grid_i},{c.grid_j}) : un seul conservé."
            )
            continue
        nodes[(c.grid_i, c.grid_j)] = c
        kept.append(c)
    if renumber:
        # Numérotation P1, P2… ligne par ligne (de bas en haut, gauche à droite)
        for n, key in enumerate(sorted(nodes, key=lambda k: (k[1], k[0])), start=1):
            nodes[key].id = f"P{n}"
    bld.columns = [nodes[k] for k in sorted(nodes, key=lambda k: (k[1], k[0]))]

    beams: dict[tuple[tuple[int, int], tuple[int, int]], Beam] = {}

    def add_beam(a: Column, c: Column, direction: str) -> None:
        span = math.hypot(a.x - c.x, a.y - c.y)
        if span > max_span:
            bld.warnings.append(
                f"Portée {a.id}–{c.id} = {span:.2f} m > {max_span} m : poutre non créée (vérifier)."
            )
            return
        width = beam_width or max(0.20, min(a.b if direction == "Y" else a.h, 0.40))
        beams[((a.grid_i, a.grid_j), (c.grid_i, c.grid_j))] = Beam(
            id="", start=a.id, end=c.id, b=round(width, 2), h=default_beam_height(span), direction=direction,
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
        for key in list(beams):
            c1, c2 = nodes[key[0]], nodes[key[1]]
            pts = [(c1.x + t * (c2.x - c1.x), c1.y + t * (c2.y - c1.y)) for t in (0.25, 0.5, 0.75)]
            ok = all(0 <= int((x - dil.x0) / dil.res) < nx and 0 <= int((y - dil.y0) / dil.res) < ny
                     and dil.mask[int((y - dil.y0) / dil.res), int((x - dil.x0) / dil.res)] for x, y in pts)
            if not ok:
                del beams[key]
    bld.beams = list(beams.values())
    for n, b in enumerate(bld.beams, start=1):
        b.id = f"N{n}"

    # Panneaux de plancher (mailles complètes)
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


WALL_LAYER_RE = re.compile(r"MUR|WALL|MACON|MAÇON|CLOISON|AGGLO|VOILE|PAROI|FACADE|FAÇADE", re.IGNORECASE)


def detect_walls(drawing: Drawing, bbox, ox: float, oy: float, keep_layers: set[str],
                 min_len: float = 1.0) -> list[list[float]]:
    """Murs = rectangles minces et longs, ou paires de traits parallèles espacés de 10 à 45 cm.

    Renvoie des axes de murs [x0, y0, x1, y1, épaisseur] dans le repère du modèle. `min_len` :
    longueur minimale d'un tronçon (abaissée pour les murs dessinés en traits morcelés).
    """
    from .slab import NON_BARRIER_RE

    x0b, y0b, x1b, y1b = bbox
    keep = {k.upper() for k in keep_layers}
    # S'il existe des calques de murs, on ne lit qu'eux (sinon cadres de fenêtres, marches… passent pour des murs)
    wall_rx = WALL_LAYER_RE
    has_wall_layers = any(wall_rx.search(sg.layer or "") for sg in drawing.segments[:200000]) or \
        any(wall_rx.search(r.layer or "") for r in drawing.rects[:200000])

    def usable(layer: str) -> bool:
        if has_wall_layers:
            return bool(layer) and (bool(wall_rx.search(layer)) or layer.upper() in keep)
        return not layer or layer.upper() in keep or not NON_BARRIER_RE.search(layer)

    walls: list[list[float]] = []
    for r in drawing.rects:
        if not usable(r.layer) or not (x0b <= r.cx <= x1b and y0b <= r.cy <= y1b):
            continue
        t, L = min(r.width, r.height), max(r.width, r.height)
        if 0.08 <= t <= 0.45 and L >= min_len:
            if r.width >= r.height:
                walls.append([r.x0 - ox, r.cy - oy, r.x1 - ox, r.cy - oy, t])
            else:
                walls.append([r.cx - ox, r.y0 - oy, r.cx - ox, r.y1 - oy, t])
    hs, vs = [], []
    edges = list(drawing.segments)
    for r in drawing.rects:  # côtés des contours fermés (murs dessinés en polylignes)
        if usable(r.layer) and max(r.width, r.height) >= min_len and min(r.width, r.height) > 0.45:
            from .geometry import Segment

            edges += [Segment(r.x0, r.y0, r.x1, r.y0, r.layer), Segment(r.x0, r.y1, r.x1, r.y1, r.layer),
                      Segment(r.x0, r.y0, r.x0, r.y1, r.layer), Segment(r.x1, r.y0, r.x1, r.y1, r.layer)]
    for sg in edges:
        if sg.dashed or not usable(sg.layer):
            continue
        if not (x0b <= min(sg.x0, sg.x1) and max(sg.x0, sg.x1) <= x1b and y0b <= min(sg.y0, sg.y1)
                and max(sg.y0, sg.y1) <= y1b):
            continue
        dx, dy = abs(sg.x1 - sg.x0), abs(sg.y1 - sg.y0)
        if dy <= 0.02 and dx >= min_len:
            hs.append((sg.y0, min(sg.x0, sg.x1), max(sg.x0, sg.x1)))
        elif dx <= 0.02 and dy >= min_len:
            vs.append((sg.x0, min(sg.y0, sg.y1), max(sg.y0, sg.y1)))
    for lines, horiz in ((hs, True), (vs, False)):
        lines.sort()
        for k, (c1, a1, b1) in enumerate(lines):
            for c2, a2, b2 in lines[k + 1:]:
                gap = c2 - c1
                if gap > 0.45:
                    break
                if gap < 0.08:
                    continue
                lo, hi = max(a1, a2), min(b1, b2)
                if hi - lo >= min_len:
                    mid = (c1 + c2) / 2
                    if horiz:
                        walls.append([lo - ox, mid - oy, hi - ox, mid - oy, gap])
                    else:
                        walls.append([mid - ox, lo - oy, mid - ox, hi - oy, gap])
                    break
    return [[round(v, 3) for v in w] for w in walls]


OPENING_CLASSES = (
    ("baie", re.compile(r"COULISS|SLIDING|BAIE", re.IGNORECASE)),
    ("porte", re.compile(r"PORTE|DOOR", re.IGNORECASE)),
    ("fenetre", re.compile(r"FENETRE|FENÊTRE|WINDOW|CHASSIS|CHÂSSIS|VITRAGE|MENUIS|NACO|OUVERTURE", re.IGNORECASE)),
)


def detect_openings(drawing: Drawing, bbox, ox: float, oy: float, mask: SlabMask | None,
                    outside=None) -> list[dict]:
    """Portes, fenêtres et baies : traits des calques de menuiserie regroupés par proximité.

    Chaque groupe donne une ouverture (largeur = plus grande dimension du groupe) ; elle est
    « en façade » si elle touche le contour du plancher.
    """
    x0b, y0b, x1b, y1b = bbox
    items: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k, _ in OPENING_CLASSES}

    def classify_layer(layer: str) -> str | None:
        if re.search(r"TEXT|COT", layer or "", re.IGNORECASE):
            return None
        for k, rx in OPENING_CLASSES:
            if rx.search(layer or ""):
                return k
        return None

    for sg in drawing.segments:
        k = classify_layer(sg.layer)
        if k and x0b <= sg.x0 <= x1b and y0b <= sg.y0 <= y1b:
            items[k].append((min(sg.x0, sg.x1), min(sg.y0, sg.y1), max(sg.x0, sg.x1), max(sg.y0, sg.y1)))
    for r in drawing.rects:
        k = classify_layer(r.layer)
        if k and x0b <= r.cx <= x1b and y0b <= r.cy <= y1b:
            items[k].append((r.x0, r.y0, r.x1, r.y1))
    out: list[dict] = []
    ny = nx = 0
    if mask is not None:
        ny, nx = mask.mask.shape
    for kind, boxes in items.items():
        if not boxes:
            continue
        # regroupement (union-find) des boîtes distantes de moins de 10 cm
        parent = list(range(len(boxes)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        tol = 0.07  # traits d'une même menuiserie ; deux baies séparées par un poteau restent distinctes
        order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
        for a_i, i in enumerate(order):
            bi = boxes[i]
            for j in order[a_i + 1:]:
                bj = boxes[j]
                if bj[0] > bi[2] + tol:
                    break
                if bj[1] <= bi[3] + tol and bj[3] >= bi[1] - tol:
                    parent[find(i)] = find(j)
        groups: dict[int, list] = {}
        for i, bx in enumerate(boxes):
            groups.setdefault(find(i), []).append(bx)
        for g in groups.values():
            xa, ya = min(b[0] for b in g), min(b[1] for b in g)
            xb, yb = max(b[2] for b in g), max(b[3] for b in g)
            w = max(xb - xa, yb - ya)
            if not 0.5 <= w <= 6.0:
                continue
            cx, cy = (xa + xb) / 2 - ox, (ya + yb) / 2 - oy
            facade = False
            if mask is not None:
                i = int((cx - mask.x0) / mask.res)
                j = int((cy - mask.y0) / mask.res)
                r = int(0.6 / mask.res)
                ext = outside if outside is not None else ~mask.mask
                win_out = ext[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
                win_in = (~ext)[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
                facade = bool(win_out.size and win_out.any() and win_in.any())
            out.append({"type": kind, "x": round(cx, 2), "y": round(cy, 2), "largeur": round(w, 2),
                        "facade": facade})
    return out
