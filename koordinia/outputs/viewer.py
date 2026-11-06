"""Données de visualisation (2D par niveau et 3D) : modele_3d.json, lu par l'application web."""
from __future__ import annotations

import json
from pathlib import Path

from ..design import ProjectResult
from ..slab import SlabMask, outline_segments


def _num(v: float, nd: int = 3) -> float:
    return round(float(v), nd)


def _segments(mask_dict: dict | None) -> list[list[float]]:
    if not mask_dict:
        return []
    return [[_num(a), _num(b), _num(c), _num(d)] for a, b, c, d in outline_segments(SlabMask.from_dict(mask_dict))]


def _rects(mask_dict: dict | None, step: float = 0.25) -> list[list[float]]:
    """Plancher décomposé en rectangles (grille grossière, bandes fusionnées) pour la 3D."""
    if not mask_dict:
        return []
    import numpy as np

    m = SlabMask.from_dict(mask_dict)
    k = max(1, int(round(step / m.res)))
    ny, nx = m.mask.shape
    a = m.mask[: ny - ny % k or ny, : nx - nx % k or nx]
    if a.shape[0] >= k and a.shape[1] >= k:
        a = a[: a.shape[0] // k * k, : a.shape[1] // k * k].reshape(a.shape[0] // k, k, a.shape[1] // k, k).mean(
            axis=(1, 3)) >= 0.5
    r = m.res * k
    out: list[list[float]] = []
    open_: dict[tuple[int, int], list[float]] = {}
    for j, row in enumerate(a):
        runs = []
        i = 0
        while i < len(row):
            if row[i]:
                s0 = i
                while i < len(row) and row[i]:
                    i += 1
                runs.append((s0, i))
            else:
                i += 1
        nxt: dict[tuple[int, int], list[float]] = {}
        for run in runs:
            if run in open_:
                rect = open_.pop(run)
                rect[3] = m.y0 + (j + 1) * r
                nxt[run] = rect
            else:
                nxt[run] = [m.x0 + run[0] * r, m.y0 + j * r, m.x0 + run[1] * r, m.y0 + (j + 1) * r]
        out += list(open_.values())
        open_ = nxt
    out += list(open_.values())
    return [[_num(v, 2) for v in rc] for rc in out]


def viewer_data(res: ProjectResult) -> dict:
    proj = res.project
    td = res.takedown
    z = 0.0
    storeys = []
    col_design = {(r.column_id, r.storey): r for r in res.columns}
    beam_design = {}
    for r in res.beams:
        beam_design[(r.beam_id, r.storey if not proj.single_plan else (proj.n - 1 if r.level == "terrasse" else -1))] = r
    for k, st in enumerate(proj.storeys):
        plan = st.plan
        cols = plan.column_map()
        columns = []
        for c in plan.columns:
            d = col_design.get((c.id, k + 1))
            columns.append({
                "id": c.id, "x": _num(c.x), "y": _num(c.y),
                "b": _num(d.design.b if d else c.b), "h": _num(d.design.h if d else c.h),
                "nu": _num(d.nu, 1) if d else None, "armatures": str(d.design.bars) if d else "",
                "cadres": str(d.design.stirrups) if d else "", "ok": bool(d.design.ok) if d else True,
            })
        beams = []
        for bm in plan.beams:
            key = (bm.id, k) if not proj.single_plan else (bm.id, proj.n - 1 if k == proj.n - 1 else -1)
            d = beam_design.get(key)
            c1, c2 = cols[bm.start], cols[bm.end]
            beams.append({
                "id": bm.id, "x1": _num(c1.x), "y1": _num(c1.y), "x2": _num(c2.x), "y2": _num(c2.y),
                "b": _num(d.design.b if d else bm.b), "h": _num(d.design.h if d else bm.h),
                "inf": str(d.design.bars_bottom) if d else "", "sup": str(d.design.bars_top) if d else "",
                "cadres": str(d.design.stirrups) if d else "", "ok": bool(d.design.ok) if d else True,
                "transfert": bool(d and d.transfer),
            })
        for t in res.transfers:
            if t.storey != k:
                continue
            tb = next(tb for tb in td.transfers if tb.id == t.beam_id)
            (_, _, xa, ya), (_, _, xb, yb) = [s[:4] for s in tb.supports]
            beams.append({"id": t.beam_id, "x1": _num(xa), "y1": _num(ya), "x2": _num(xb), "y2": _num(yb),
                          "b": _num(t.design.b), "h": _num(t.design.h), "inf": str(t.design.bars_bottom),
                          "sup": str(t.design.bars_top), "cadres": str(t.design.stirrups),
                          "ok": bool(t.design.ok), "transfert": True, "auto": True})
        zones = []
        for zz in plan.zones or []:
            zones.append({"nom": zz["name"], "usage": zz["usage"], "type": zz["type"], "q": zz.get("q"),
                          "surface": zz["area"], "contour": _segments(zz["cells"])})
        storeys.append({
            "nom": st.name, "plancher": proj.floor_label(k), "altitude": _num(z, 2), "hauteur": _num(st.height, 2),
            "planche": st.sheet, "colonnes": columns, "poutres": beams, "zones": zones,
            "contour": _segments(plan.slab), "dalle": _rects(plan.slab), "surface": _num(td.storeys[k].slab_area, 1),
            "axes_x": [[_num(v), n] for v, n in zip(plan.grid_x, plan.axis_x or [str(i + 1) for i in range(len(plan.grid_x))])],
            "axes_y": [[_num(v), n] for v, n in zip(plan.grid_y, plan.axis_y or [chr(65 + j % 26) for j in range(len(plan.grid_y))])],
        })
        z += st.height
    footings = [{"id": f.column_id, "x": _num(f.x), "y": _num(f.y), "A": _num(f.design.A), "B": _num(f.design.B),
                 "h": _num(f.design.h), "sous_mur": f.on_wall, "ok": bool(f.design.ok)} for f in res.footings]
    if proj.single_plan:  # positions des semelles = poteaux du plan
        cmap = proj.storeys[0].plan.column_map()
        for f in footings:
            if f["id"] in cmap:
                f["x"], f["y"] = _num(cmap[f["id"]].x), _num(cmap[f["id"]].y)
    n_ko = sum(not r.design.ok for r in res.columns) + sum(not r.design.ok for r in res.beams) \
        + sum(not f.design.ok for f in res.footings)
    return {
        "projet": proj.name, "norme": res.code.name, "sol_MPa": res.sigma_sol, "fondations": res.foundation_type,
        "niveaux": storeys, "terrasse": _num(z, 2), "semelles": footings, "non_verifies": n_ko,
        "avertissements": list(dict.fromkeys(res.warnings)),
        "radier": res.raft, "pieux": res.piles,
        "balcons": [{"plancher": b.floor, "nom": b.name, "porte_a_faux": b.length, "epaisseur": b.h,
                     "chapeaux": b.bars_top} for b in res.balconies],
        "escaliers": [{"volee": s.floor, "marches": s.risers, "h": s.riser_h, "g": s.going,
                       "paillasse": s.thickness, "inf": s.bars_bottom} for s in res.stairs],
    }


def write_viewer(res: ProjectResult, folder: Path) -> Path:
    path = folder / "modele_3d.json"
    path.write_text(json.dumps(viewer_data(res), ensure_ascii=False, default=lambda o: o.item()
                               if hasattr(o, "item") else str(o)), encoding="utf-8")
    return path
