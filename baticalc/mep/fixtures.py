"""Appareils sanitaires lus sur le plan : blocs nommés, sinon géométrie des équipements dans
les pièces d'eau, sinon estimation d'après le nom et la surface de la pièce."""
from __future__ import annotations

import math
import re

from ..geometry import Drawing
from ..slab import SlabMask

BLOCK_RE = [
    ("wc", re.compile(r"\bW\.?C\b|WC|TOILET|CUVETTE|SUSPENDU|TURQUE", re.I)),
    ("urinoir", re.compile(r"URIN", re.I)),
    ("douche", re.compile(r"DOUCHE|SHOWER|RECEVEUR", re.I)),
    ("lavabo", re.compile(r"LAVABO|VASQUE|LAVE.?MAIN|SINK|BASIN", re.I)),
    ("evier", re.compile(r"EVIER|ÉVIER|KITCHEN", re.I)),
]
EQUIP_LAYER_RE = re.compile(r"EQUIP|SANIT|APPAREIL|PLOMB|MOBIL|FIXTURE|PLUMB", re.I)
WET_NAME_RE = re.compile(r"W\.?C|TOIL|DOUCHE|SANIT|SDB|SALLE D.?EAU|SALLE DE BAIN|VESTI|LAVABO|CUISINE|KITCH", re.I)


def _room_masks(rooms: list[dict]) -> list[tuple[dict, SlabMask]]:
    return [(z, SlabMask.from_dict(z["cells"])) for z in rooms]


def _in(mask: SlabMask, x: float, y: float) -> bool:
    i, j = int((x - mask.x0) / mask.res), int((y - mask.y0) / mask.res)
    ny, nx = mask.mask.shape
    return 0 <= i < nx and 0 <= j < ny and bool(mask.mask[j, i])


def _classify_shape(w: float, h: float) -> str | None:
    a, b = max(w, h), min(w, h)
    if a < 0.25 or a > 1.6:
        return None
    if 0.70 <= a <= 1.10 and b >= 0.65 and a / b < 1.35:
        return "douche"
    if 0.55 <= a <= 0.90 and 0.30 <= b <= 0.55 and a / b >= 1.3:
        return "wc"
    if a <= 0.70 and b >= 0.25:
        return "lavabo"
    if a > 1.10 and b <= 0.70:
        return "evier"
    return None


def estimate_from_room(z: dict) -> list[str]:
    """Équipement par défaut d'une pièce d'eau d'après son nom et sa surface."""
    name = z["name"].upper()
    area = z["area"]
    if re.search(r"DOUCHE", name):
        return ["douche"] * max(1, round(area / 2.0)) + ["lavabo"]
    if re.search(r"VESTI", name):
        return ["douche"] * max(1, round(area / 4.0)) + ["lavabo"] * max(1, round(area / 4.0))
    if re.search(r"CUISINE|KITCH", name):
        return ["evier"]
    if re.search(r"SDB|SALLE D.?EAU|SALLE DE BAIN", name):
        return ["wc", "lavabo", "douche"]
    n_wc = max(1, round(area / 2.5))
    out = ["wc"] * n_wc + ["lavabo"] * max(1, math.ceil(n_wc / 2))
    if re.search(r"HOM|HOMME|MESSIEURS|H\b", name) and n_wc >= 2:
        out += ["urinoir"] * max(1, n_wc // 2)
    return out


def detect_fixtures(drawing: Drawing, rooms: list[dict], ox: float, oy: float) -> list[dict]:
    """Appareils sanitaires : 1) blocs nommés ; 2) étiquettes des pièces d'eau (« W.C », « Douche »,
    « Toilettes »…) ; 3) tracés sur des calques explicitement sanitaires."""
    from ..zones import load_catalogue, read_labels

    out: list[dict] = []
    # 1) blocs nommés
    for mk in drawing.marks:
        if mk.kind != "BLOCK":
            continue
        kind = next((k for k, rx in BLOCK_RE if rx.search(mk.name)), None)
        if kind:
            out.append({"type": kind, "x": round((mk.x0 + mk.x1) / 2 - ox, 2), "y": round((mk.y0 + mk.y1) / 2 - oy, 2),
                        "local": mk.name, "source": "bloc"})
    if out:
        return out
    # 2) étiquettes des pièces d'eau
    labels = [lb for lb in read_labels(drawing, load_catalogue()) if WET_NAME_RE.search(lb.name)]
    wc_labels = [(lb.x - ox, lb.y - oy) for lb in labels if re.match(r"^\s*W\.?\s?C\b", lb.name, re.I)]
    for lb in labels:
        x, y = lb.x - ox, lb.y - oy
        name = lb.name.upper()
        area = lb.area or 3.0
        items: list[str]
        if re.match(r"^\s*W\.?\s?C\b", name):
            items = ["wc"]
        elif "DOUCHE" in name:
            items = ["douche"]
        elif re.search(r"VESTI", name):
            items = ["douche"] * max(1, round(area / 4)) + ["lavabo"] * max(1, round(area / 4))
        elif re.search(r"CUISINE|KITCH", name):
            items = ["evier"]
        elif re.search(r"SDB|SALLE D.?EAU|SALLE DE BAIN", name):
            items = ["wc", "lavabo", "douche"]
        else:  # toilettes / sanitaires : lavabos ; WC seulement sans cabines « W.C » étiquetées autour
            items = ["lavabo"] * max(1, round(area / 6))
            if not any(math.hypot(x - a, y - b) < 6.0 for a, b in wc_labels):
                n_wc = max(1, round(area / 3))
                items += ["wc"] * n_wc
                if re.search(r"HOM|HOMME|MESSIEURS", name) and n_wc >= 2:
                    items += ["urinoir"] * (n_wc // 2)
        for k, kind in enumerate(items):
            out.append({"type": kind, "x": round(x + 0.5 * (k % 3), 2), "y": round(y - 0.5 * (k // 3), 2),
                        "local": lb.name, "source": "étiquette"})
    if out:
        return out
    # 3) tracés sur calques sanitaires explicites
    strict = re.compile(r"SANIT|APPAREIL|PLOMB|FIXTURE|PLUMB", re.I)
    boxes = [(r.x0 - ox, r.y0 - oy, r.x1 - ox, r.y1 - oy) for r in drawing.rects if strict.search(r.layer or "")]
    for b in boxes:
        kind = _classify_shape(b[2] - b[0], b[3] - b[1])
        if kind:
            out.append({"type": kind, "x": round((b[0] + b[2]) / 2, 2), "y": round((b[1] + b[3]) / 2, 2),
                        "local": "", "source": "tracé"})
    return out
