"""Locaux et usages : lecture des étiquettes de pièces, délimitation des locaux,
charges par local, trémies, balcons, terrasses et espaces verts sur dalle.

Les règles sont dans un catalogue JSON modifiable (koordinia/data/usages.json),
complétable par projet (clé « usages » de koordinia.json).
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import Drawing
from .slab import SlabMask, _dilate, wall_raster

CATALOGUE_PATH = Path(__file__).parent / "data" / "usages.json"
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*[²2]", re.IGNORECASE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


@dataclass
class Usage:
    nom: str
    motifs: list[str]
    q: float | None = None
    g_finitions: float | None = None
    g_total: float | None = None
    type: str = "local"          # local, ouverture, balcon, exterieur, escalier
    note: str = ""

    def matches(self, name: str) -> bool:
        n = _norm(name)
        return any(re.search(m, n) for m in self.motifs)


def load_catalogue(extra: list[dict] | None = None, path: str | Path | None = None) -> list[Usage]:
    """Catalogue d'usages ; les règles `extra` (projet) sont prioritaires."""
    data = json.loads(Path(path or CATALOGUE_PATH).read_text(encoding="utf-8"))
    rules = list(extra or []) + data["usages"]
    out = []
    for r in rules:
        r = {k: v for k, v in r.items() if not k.startswith("_")}
        if isinstance(r.get("motifs"), str):
            r["motifs"] = [r["motifs"]]
        out.append(Usage(**r))
    return out


def classify(name: str, catalogue: list[Usage]) -> Usage | None:
    for u in catalogue:
        if u.matches(name):
            return u
    return None


@dataclass
class RoomLabel:
    x: float
    y: float
    name: str
    area: float | None = None


def read_labels(drawing: Drawing, catalogue: list[Usage]) -> list[RoomLabel]:
    """Étiquettes de locaux : nom reconnu par le catalogue, surface écrite à côté si présente."""
    names: list[RoomLabel] = []
    areas: list[tuple[float, float, float]] = []
    for t in drawing.texts:
        txt = " ".join(t.text.split())
        if not txt or len(txt) > 70:
            continue
        m = AREA_RE.search(txt)
        area = float(m.group(1).replace(",", ".")) if m else None
        name = AREA_RE.sub("", txt).strip(" :-")
        if not re.search(r"[A-Za-zÀ-ÿ]{2,}", name):
            if area:
                areas.append((t.x, t.y, area))  # surface seule : rattachée au nom le plus proche
            continue
        if classify(name, catalogue) is None:
            continue
        names.append(RoomLabel(t.x, t.y, name, area))
    for lb in names:
        if lb.area is None and areas:
            k = min(range(len(areas)), key=lambda i: (areas[i][0] - lb.x) ** 2 + (areas[i][1] - lb.y) ** 2)
            ax, ay, a = areas[k]
            if ((ax - lb.x) ** 2 + (ay - lb.y) ** 2) ** 0.5 <= 1.5:
                lb.area = a
                areas.pop(k)
    return names


@dataclass
class Zone:
    name: str            # nom écrit sur le plan
    usage: str           # nom de l'usage du catalogue
    type: str
    q: float | None
    g_finitions: float | None
    g_total: float | None
    area: float          # surface délimitée (m²)
    area_label: float | None
    approx: bool         # délimitation approchée (surface de l'étiquette)
    cells: dict          # SlabMask.to_dict() de la zone
    note: str = ""
    x: float = 0.0
    y: float = 0.0

    def mask(self) -> SlabMask:
        return SlabMask.from_dict(self.cells)


BALCONY_SLAB = 4.0  # dalle pleine de balcon ≈ 16 cm × 25 kN/m³ (kN/m²)

PRIORITY = {"ouverture": 0, "escalier": 1, "balcon": 2, "exterieur": 3, "local": 4}


def detect_zones(
    drawing: Drawing,
    grid: SlabMask,
    ox: float,
    oy: float,
    catalogue: list[Usage],
    *,
    keep_layers: set[str] | None = None,
    door: float = 0.95,
) -> tuple[list[dict], list[str]]:
    """Délimite chaque local étiqueté sur la grille `grid` (repère du modèle).

    Remplissage depuis l'étiquette jusqu'aux murs (portes ≤ `door` m refermées). Si le
    remplissage « fuit » (surface > 2,5 × la surface écrite), on retient un carré de la
    surface écrite centré sur l'étiquette, signalé comme approché.
    """
    notes: list[str] = []
    res = grid.res
    ny, nx = grid.mask.shape
    bbox = (grid.x0 + ox, grid.y0 + oy, grid.x0 + ox + nx * res, grid.y0 + oy + ny * res)

    def raster(ortho: bool) -> np.ndarray | None:
        w = wall_raster(drawing, bbox, res=res, keep_layers=keep_layers, drop_small=0.6, orthogonal_only=ortho)
        if w is None:
            return None
        out = np.zeros_like(grid.mask)
        out[:min(ny, w.shape[0]), :min(nx, w.shape[1])] = w[:ny, :nx]
        return out

    walls = {False: raster(False), True: raster(True)}
    if walls[False] is None:
        return [], notes
    barriers: dict[tuple[bool, int], np.ndarray] = {}
    taken = np.zeros_like(grid.mask)
    labels = read_labels(drawing, catalogue)
    labels.sort(key=lambda lb: PRIORITY.get(classify(lb.name, catalogue).type, 9))
    zones: list[dict] = []

    def fill(j0: int, i0: int, ortho: bool, rad: int, limit: int) -> tuple[np.ndarray | None, bool]:
        key = (ortho, rad)
        if key not in barriers:
            barriers[key] = _dilate(walls[ortho], rad) if rad else walls[ortho].copy()
        barrier = barriers[key]
        start = None
        for r in range(0, int(0.8 / res)):
            for dj in range(-r, r + 1):
                for di in ((-r, r) if abs(dj) != r else range(-r, r + 1)):
                    a, b = j0 + dj, i0 + di
                    if 0 <= a < ny and 0 <= b < nx and not barrier[a, b] and not taken[a, b]:
                        start = (a, b)
                        break
                if start:
                    break
            if start:
                break
        if start is None:
            return None, True
        region = np.zeros_like(grid.mask)
        q: deque[tuple[int, int]] = deque([start])
        region[start] = True
        count = 1
        while q and count <= limit:
            j, i = q.popleft()
            for a, b in ((j + 1, i), (j - 1, i), (j, i + 1), (j, i - 1)):
                if 0 <= a < ny and 0 <= b < nx and not region[a, b] and not barrier[a, b] and not taken[a, b]:
                    region[a, b] = True
                    count += 1
                    q.append((a, b))
        if count > limit:
            return None, True
        if rad:
            region = _dilate(region, rad) & ~walls[ortho] & ~taken
        return region, False

    for lb in labels:
        u = classify(lb.name, catalogue)
        i0 = int((lb.x - ox - grid.x0) / res)
        j0 = int((lb.y - oy - grid.y0) / res)
        if not (0 <= i0 < nx and 0 <= j0 < ny):
            continue
        ortho = u.type == "ouverture"
        limit = int(2.5 * lb.area / res ** 2) if lb.area else int((25.0 if ortho else 0.25 * nx * ny * res ** 2) / res ** 2)
        # plusieurs fermetures de portes : on garde la surface la plus proche de celle écrite
        best, best_score = None, None
        for door_w in (door, 0.5, 0.2):
            rad = int(round(door_w / 2 / res))
            region, leaked = fill(j0, i0, ortho, rad, limit)
            if leaked or region is None or not region.any():
                continue
            area = float(region.sum()) * res ** 2
            score = abs(np.log(area / lb.area)) if lb.area else 0.0
            if best is None or score < best_score - 1e-9:
                best, best_score = region, score
            if not lb.area or score < np.log(1.15):
                break
        approx = False
        region = best
        if region is not None and float(region.sum()) * res ** 2 < 0.3:
            continue  # reliquat minuscule (étiquette en double dans un local déjà délimité)
        if region is not None and lb.area and u.type in ("escalier", "ouverture", "exterieur") \
                and not (0.6 <= float(region.sum()) * res ** 2 / lb.area <= 1.6):
            region = None  # marches / croix / garde-corps découpent la zone : surface écrite retenue
        if region is None:
            if lb.area:
                side = lb.area ** 0.5
            elif ortho:
                side = 2.0
                notes.append(f"Trémie « {lb.name} » : contour non trouvé, trémie de 2,0 × 2,0 m supposée.")
            else:
                notes.append(f"Local « {lb.name} » : contour non fermé et surface non indiquée — ignoré.")
                continue
            region = np.zeros_like(grid.mask)
            ia, ib = int((lb.x - ox - side / 2 - grid.x0) / res), int((lb.x - ox + side / 2 - grid.x0) / res)
            ja, jb = int((lb.y - oy - side / 2 - grid.y0) / res), int((lb.y - oy + side / 2 - grid.y0) / res)
            region[max(0, ja):max(0, jb), max(0, ia):max(0, ib)] = True
            region &= ~taken
            if u.type == "exterieur":
                region &= ~grid.mask  # terrasse / jardin approché : hors de l'emprise bâtie
            else:
                region &= grid.mask   # local approché : dans le plancher
            approx = True
            if lb.area:
                notes.append(f"Local « {lb.name} » : contour non fermé, zone approchée par sa surface écrite "
                             f"({lb.area:.2f} m²).")
        if not region.any():
            continue
        if u.type == "ouverture" and not approx:
            region = (_dilate(region, 1) | region) & ~taken  # trémie mesurée jusqu'à son trait de contour
        area = float(region.sum()) * res ** 2
        if lb.area and not approx and not (0.6 * lb.area <= area <= 1.6 * lb.area):
            notes.append(f"Local « {lb.name} » : surface délimitée {area:.1f} m² ≠ {lb.area:.2f} m² écrits "
                         "(contour à vérifier).")
        taken |= region
        zm = SlabMask(res, grid.x0, grid.y0, region)
        zones.append({
            "name": lb.name, "usage": u.nom, "type": u.type, "q": u.q, "g_finitions": u.g_finitions,
            "g_total": u.g_total, "area": round(area, 2), "area_label": lb.area, "approx": approx,
            "cells": zm.to_dict(), "note": u.note, "x": round(lb.x - ox, 2), "y": round(lb.y - oy, 2),
        })
    return zones, notes


def zone_objects(plan) -> list[Zone]:
    return [Zone(**z) for z in (plan.zones or [])]


def cell_loads(mask: SlabMask, zones: list[Zone], g_default: float, q_default: float, g_slab: float,
               roof: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[Zone, np.ndarray]]]:
    """Charges G et Q de chaque cellule du plancher (ordre de `mask.centers()`), trémies retirées.

    Renvoie (masque effectif, g par cellule, q par cellule, [(zone, sélection des cellules)]).
    """
    eff = mask.mask.copy()
    zm_list = []
    for z in zones:
        zm = z.mask()
        if zm.mask.shape != eff.shape or zm.x0 != mask.x0 or zm.y0 != mask.y0:
            continue  # grille différente (modèle édité) : zone ignorée
        if z.type == "ouverture":
            eff &= ~zm.mask
        elif not roof:
            zm_list.append((z, zm.mask))
    jj, ii = np.nonzero(eff)
    g = np.full(len(jj), g_default)
    q = np.full(len(jj), q_default)
    sel_list = []
    for z, zmask in zm_list:
        sel = zmask[jj, ii]
        if not sel.any():
            continue
        if z.q is not None:
            q[sel] = z.q
        if z.g_total is not None:
            g[sel] = z.g_total
        elif z.type == "balcon":
            g[sel] = BALCONY_SLAB + (z.g_finitions if z.g_finitions is not None else 1.0)
        elif z.g_finitions is not None:
            g[sel] = g_slab + z.g_finitions
        sel_list.append((z, sel))
    return eff, g, q, sel_list
