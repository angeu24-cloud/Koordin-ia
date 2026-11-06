"""Import IFC (Revit, ArchiCAD, Tekla, Robot, CYPECAD, Graitec…) vers un projet Koordin-IA.

Lecture des niveaux (IfcBuildingStorey), poteaux (IfcColumn), poutres (IfcBeam),
dalles (IfcSlab), murs (IfcWall) et locaux (IfcSpace), à partir de leur géométrie
réelle (moteur géométrique d'IfcOpenShell, coordonnées globales).

Convention Koordin-IA : l'étage k porte le plancher situé à l'altitude du niveau k+1.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..model import Beam, Building, Column
from ..project import Project, Storey
from ..recognition import build_frame
from ..slab import SlabMask


def _shapes(f, types: tuple[str, ...]):
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    for t in types:
        for el in f.by_type(t):
            if not getattr(el, "Representation", None):
                continue
            try:
                sh = ifcopenshell.geom.create_shape(settings, el)
            except Exception:  # noqa: BLE001 — géométrie illisible : élément ignoré
                continue
            v = np.array(sh.geometry.verts, dtype=float).reshape(-1, 3)
            faces = np.array(sh.geometry.faces, dtype=int).reshape(-1, 3)
            if len(v):
                yield el, v, faces


def _length_scale(f) -> float:
    try:
        import ifcopenshell.util.unit

        return float(ifcopenshell.util.unit.calculate_unit_scale(f))
    except Exception:  # noqa: BLE001
        return 1.0


def _rasterize(polys: list[tuple[np.ndarray, np.ndarray]], bbox, res: float = 0.10) -> SlabMask:
    """Projection au sol de faces triangulées (dalles, locaux) sur une grille."""
    x0, y0, x1, y1 = bbox
    nx, ny = int((x1 - x0) / res) + 1, int((y1 - y0) / res) + 1
    m = np.zeros((ny, nx), dtype=bool)
    gx = x0 + (np.arange(nx) + 0.5) * res
    gy = y0 + (np.arange(ny) + 0.5) * res
    for v, faces in polys:
        for tri in faces:
            p = v[tri, :2]
            ax, ay = p[:, 0].min(), p[:, 1].min()
            bx, by = p[:, 0].max(), p[:, 1].max()
            i0, i1 = max(0, int((ax - x0) / res)), min(nx, int((bx - x0) / res) + 1)
            j0, j1 = max(0, int((ay - y0) / res)), min(ny, int((by - y0) / res) + 1)
            if i1 <= i0 or j1 <= j0:
                continue
            X, Y = np.meshgrid(gx[i0:i1], gy[j0:j1])
            (xa, ya), (xb, yb), (xc, yc) = p
            d = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc)
            if abs(d) < 1e-12:
                continue
            l1 = ((yb - yc) * (X - xc) + (xc - xb) * (Y - yc)) / d
            l2 = ((yc - ya) * (X - xc) + (xa - xc) * (Y - yc)) / d
            inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l1 + l2 <= 1 + 1e-9)
            m[j0:j1, i0:i1] |= inside
    return SlabMask(res, x0, y0, m)


def import_ifc(path: str | Path, *, max_span: float = 8.0) -> Project:
    import ifcopenshell

    f = ifcopenshell.open(str(path))
    scale = _length_scale(f)
    proj = Project(source=str(path), name=(f.by_type("IfcProject") or [None])[0].Name or Path(path).stem)
    storeys = sorted(f.by_type("IfcBuildingStorey"), key=lambda s: (s.Elevation or 0.0))
    elev = [float(s.Elevation or 0.0) * scale for s in storeys]
    if len(storeys) < 1:
        raise ValueError("Aucun niveau (IfcBuildingStorey) dans le fichier IFC.")

    cols, beams, slabs, walls, spaces = [], [], [], [], []
    for el, v, faces in _shapes(f, ("IfcColumn",)):
        lo, hi = v.min(0), v.max(0)
        cols.append((el, (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[0] - lo[0], hi[1] - lo[1], lo[2], hi[2]))
    for el, v, faces in _shapes(f, ("IfcBeam",)):
        lo, hi = v.min(0), v.max(0)
        beams.append((el, lo, hi))
    for el, v, faces in _shapes(f, ("IfcSlab",)):
        if (getattr(el, "PredefinedType", None) or "") in ("BASESLAB",):
            continue
        slabs.append((el, v, faces, v[:, 2].max()))
    for el, v, faces in _shapes(f, ("IfcWall", "IfcWallStandardCase")):
        lo, hi = v.min(0), v.max(0)
        walls.append((lo, hi))
    for el, v, faces in _shapes(f, ("IfcSpace",)):
        spaces.append((el, v, faces, v[:, 2].min()))
    if not cols:
        raise ValueError("Aucun poteau (IfcColumn) dans le fichier IFC.")

    all_xy = np.array([[c[1], c[2]] for c in cols])
    pad = 5.0
    bbox = (all_xy[:, 0].min() - pad, all_xy[:, 1].min() - pad, all_xy[:, 0].max() + pad, all_xy[:, 1].max() + pad)
    ox, oy = float(all_xy[:, 0].min()), float(all_xy[:, 1].min())

    # niveaux : altitudes + toit (sommet des poteaux les plus hauts)
    top = max(c[6] for c in cols)
    levels = elev + ([top] if top > elev[-1] + 1.0 else [])
    n_storeys = len(levels) - 1
    if n_storeys < 1:
        raise ValueError("Un seul niveau et pas de poteaux au-dessus : modèle incomplet.")

    from ..zones import classify, load_catalogue

    catalogue = load_catalogue()
    gid: dict[tuple[int, int], str] = {}

    def global_id(x: float, y: float) -> str:
        key = (round(x / 0.3), round(y / 0.3))
        for (a, b), v in gid.items():
            if abs(a - key[0]) <= 1 and abs(b - key[1]) <= 1:
                return v
        gid[key] = f"P{len(gid) + 1}"
        return gid[key]

    for k in range(n_storeys):
        z0, z1 = levels[k], levels[k + 1]
        plan = Building(n_levels=1, floor_height=z1 - z0, source=str(path))
        plan.origin = [ox, oy]
        seen = set()
        for el, x, y, b, h, zl, zh in sorted(cols, key=lambda c: (c[2], c[1])):
            if zl < z1 - 0.3 and zh > z0 + 0.3:  # le poteau traverse l'étage
                cid = global_id(x, y)
                if cid in seen:
                    continue
                seen.add(cid)
                plan.columns.append(Column(cid, round(x - ox, 3), round(y - oy, 3), round(b, 3), round(h, 3)))
        # plancher haut : dalles dont la face supérieure est au niveau z1
        polys = [(v - [ox, oy, 0], faces) for el, v, faces, ztop in slabs if abs(ztop - z1) <= 0.6]
        if polys:
            sb = (bbox[0] - ox, bbox[1] - oy, bbox[2] - ox, bbox[3] - oy)
            mask = _rasterize(polys, sb)
            plan.slab = mask.to_dict()
            plan.footprint = plan.slab
        else:
            mask = None
            proj.warnings.append(f"Niveau {storeys[min(k, len(storeys) - 1)].Name} : aucune dalle à "
                                 f"+{z1:.2f} m dans l'IFC, mailles de la trame utilisées.")
        # murs porteurs de l'étage (axes)
        for lo, hi in walls:
            if hi[2] > z0 + 0.3 and lo[2] < z1 - 0.3:
                dx, dy = hi[0] - lo[0], hi[1] - lo[1]
                if dx >= dy and dy <= 0.45:
                    plan.walls.append([lo[0] - ox, (lo[1] + hi[1]) / 2 - oy, hi[0] - ox, (lo[1] + hi[1]) / 2 - oy, dy])
                elif dy > dx and dx <= 0.45:
                    plan.walls.append([(lo[0] + hi[0]) / 2 - ox, lo[1] - oy, (lo[0] + hi[0]) / 2 - ox, hi[1] - oy, dx])
        build_frame(plan, mask, max_span=max_span, renumber=False)
        # poutres de l'IFC : on retient leurs sections quand elles relient deux poteaux du modèle
        cmap = {(round(c.x, 1), round(c.y, 1)): c for c in plan.columns}
        for el, lo, hi in beams:
            if abs(hi[2] - z1) > 0.6:
                continue
            for bm in plan.beams:
                c1, c2 = plan.column_map()[bm.start], plan.column_map()[bm.end]
                mx, my = (c1.x + c2.x) / 2 + ox, (c1.y + c2.y) / 2 + oy
                if lo[0] - 0.3 <= mx <= hi[0] + 0.3 and lo[1] - 0.3 <= my <= hi[1] + 0.3:
                    width = min(hi[0] - lo[0], hi[1] - lo[1])
                    bm.b, bm.h = round(max(0.15, width), 2), round(max(0.2, hi[2] - lo[2]), 2)
        del cmap
        # locaux (IfcSpace) du niveau supérieur → usages
        for el, v, faces, zmin in spaces:
            if abs(zmin - z1) > 0.6 or mask is None:
                continue
            name = " ".join(x for x in (el.LongName, el.Name) if x)
            u = classify(name, catalogue) if name else None
            if not u:
                continue
            zm = _rasterize([(v - [ox, oy, 0], faces)], (mask.x0, mask.y0, mask.x0 + mask.mask.shape[1] * mask.res,
                                                       mask.y0 + mask.mask.shape[0] * mask.res))
            zm.mask = zm.mask[:mask.mask.shape[0], :mask.mask.shape[1]]
            plan.zones.append({"name": name, "usage": u.nom, "type": u.type, "q": u.q, "g_finitions": u.g_finitions,
                               "g_total": u.g_total, "area": round(zm.area, 2), "area_label": None, "approx": False,
                               "cells": SlabMask(mask.res, mask.x0, mask.y0, zm.mask).to_dict(), "note": u.note,
                               "x": 0.0, "y": 0.0})
        name = storeys[k].Name if k < len(storeys) else f"Niveau {k + 1}"
        proj.storeys.append(Storey(name or f"Niveau {k + 1}", round(float(z1 - z0), 3), plan, f"IFC : {Path(path).name}"))
    proj.warnings.append(f"Import IFC : {len(cols)} poteaux, {len(beams)} poutres, {len(slabs)} dalles, "
                         f"{len(walls)} murs, {len(spaces)} locaux lus ; {n_storeys} étage(s).")
    return proj
