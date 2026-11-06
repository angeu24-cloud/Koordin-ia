"""Plans d'exécution au format DXF (ouvrables dans AutoCAD, BricsCAD, DraftSight…).

Unité de dessin : le mètre ($INSUNITS = 6).
"""
from __future__ import annotations

import math
import string
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import numpy as np
from ezdxf.enums import TextEntityAlignment

from ..design import ProjectResult
from ..codes.common import Bars

LAYERS = {
    "AXES": (1, "CENTER"),
    "COFFRAGE": (7, "Continuous"),
    "POTEAUX": (7, "Continuous"),
    "POUTRES": (3, "DASHED"),
    "SEMELLES": (5, "Continuous"),
    "ACIERS": (1, "Continuous"),
    "CADRES": (2, "Continuous"),
    "TEXTE": (7, "Continuous"),
    "COTATION": (8, "Continuous"),
    "CARTOUCHE": (7, "Continuous"),
    "PLANCHER": (4, "Continuous"),
    "LOCAUX": (6, "Continuous"),
    "TREMIES": (1, "Continuous"),
}


def axis_name_x(i: int) -> str:
    return str(i + 1)


def axis_name_y(j: int) -> str:
    letters = string.ascii_uppercase
    return letters[j] if j < 26 else letters[j // 26 - 1] + letters[j % 26]


def _new_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    doc.header["$LTSCALE"] = 0.02
    for name, (color, lt) in LAYERS.items():
        doc.layers.add(name, color=color, linetype=lt)
    doc.dimstyles.duplicate_entry("EZDXF", "KOORD")
    ds = doc.dimstyles.get("KOORD")
    ds.dxf.dimtxt = 0.15
    ds.dxf.dimasz = 0.10
    ds.dxf.dimexe = 0.05
    ds.dxf.dimexo = 0.05
    ds.dxf.dimdec = 2
    ds.dxf.dimlfac = 1.0
    return doc


def _text(msp, x, y, txt, h=0.15, layer="TEXTE", align=TextEntityAlignment.MIDDLE_CENTER, rot=0.0):
    t = msp.add_text(txt, height=h, rotation=rot, dxfattribs={"layer": layer})
    t.set_placement((x, y), align=align)
    return t


def _rect(msp, x0, y0, x1, y1, layer):
    return msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def _cartouche(msp, x, y, title: str, res: ProjectResult, subtitle: str = ""):
    _rect(msp, x, y, x + 7.0, y + 1.6, "CARTOUCHE")
    _text(msp, x + 3.5, y + 1.25, title, 0.25, "CARTOUCHE")
    sub = subtitle or f"Règlement : {res.code.name}"
    if res.project.name:
        sub = f"{res.project.name} — {sub}"
    _text(msp, x + 3.5, y + 0.85, sub, 0.14, "CARTOUCHE")
    _text(msp, x + 3.5, y + 0.50, f"Source : {Path(res.project.source.split(' (')[0]).name}", 0.12, "CARTOUCHE")
    _text(msp, x + 3.5, y + 0.20, "BatiCalc — document à vérifier et viser par l'ingénieur structure",
          0.10, "CARTOUCHE")


def _axes(msp, res: ProjectResult, ext: float = 1.5, plan=None):
    b = plan or res.building
    if not b.grid_x or not b.grid_y:
        return
    x0, x1 = min(b.grid_x) - ext, max(b.grid_x) + ext
    y0, y1 = min(b.grid_y) - ext, max(b.grid_y) + ext
    names_x = b.axis_x if len(b.axis_x) == len(b.grid_x) else [axis_name_x(i) for i in range(len(b.grid_x))]
    names_y = b.axis_y if len(b.axis_y) == len(b.grid_y) else [axis_name_y(j) for j in range(len(b.grid_y))]
    for i, x in enumerate(b.grid_x):
        msp.add_line((x, y0), (x, y1), dxfattribs={"layer": "AXES"})
        msp.add_circle((x, y1 + 0.3), 0.3, dxfattribs={"layer": "AXES"})
        _text(msp, x, y1 + 0.3, names_x[i], 0.25, "AXES")
    for j, y in enumerate(b.grid_y):
        msp.add_line((x0, y), (x1, y), dxfattribs={"layer": "AXES"})
        msp.add_circle((x0 - 0.3, y), 0.3, dxfattribs={"layer": "AXES"})
        _text(msp, x0 - 0.3, y, names_y[j], 0.25, "AXES")
    # Chaînes de cotes entre axes + cote totale
    yd = min(b.grid_y) - ext + 0.4
    for xa, xb in zip(b.grid_x, b.grid_x[1:]):
        msp.add_linear_dim(base=(xa, yd), p1=(xa, min(b.grid_y)), p2=(xb, min(b.grid_y)),
                           dimstyle="KOORD", dxfattribs={"layer": "COTATION"}).render()
    if len(b.grid_x) > 2:
        msp.add_linear_dim(base=(b.grid_x[0], yd - 0.5), p1=(b.grid_x[0], min(b.grid_y)),
                           p2=(b.grid_x[-1], min(b.grid_y)), dimstyle="KOORD",
                           dxfattribs={"layer": "COTATION"}).render()
    xd = max(b.grid_x) + ext - 0.4
    for ya, yb in zip(b.grid_y, b.grid_y[1:]):
        msp.add_linear_dim(base=(xd, ya), p1=(max(b.grid_x), ya), p2=(max(b.grid_x), yb), angle=90,
                           dimstyle="KOORD", dxfattribs={"layer": "COTATION"}).render()


def _slab_outline(msp, bld, layer: str = "PLANCHER") -> None:
    if not bld.slab:
        return
    from ..slab import SlabMask, outline_segments

    for x0, y0, x1, y1 in outline_segments(SlabMask.from_dict(bld.slab)):
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": layer})


def _draw_zones(msp, bld, roof: bool) -> None:
    """Contours des locaux à charge particulière (balcons, terrasses, locaux lourds) et trémies."""
    from ..slab import SlabMask, outline_segments

    for z in bld.zones or []:
        if roof and z["type"] != "ouverture":
            continue
        if z["type"] == "local" and (z.get("q") is None or z.get("usage") == "Bureaux"):
            continue  # locaux courants : pas de repérage
        zm = SlabMask.from_dict(z["cells"])
        layer = "TREMIES" if z["type"] == "ouverture" else "LOCAUX"
        for x0, y0, x1, y1 in outline_segments(zm):
            msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": layer})
        jj, ii = np.nonzero(zm.mask)
        if len(jj) == 0:
            continue
        xa, xb = zm.x0 + ii.min() * zm.res, zm.x0 + (ii.max() + 1) * zm.res
        ya, yb = zm.y0 + jj.min() * zm.res, zm.y0 + (jj.max() + 1) * zm.res
        if z["type"] == "ouverture":
            msp.add_line((xa, ya), (xb, yb), dxfattribs={"layer": layer})
            msp.add_line((xa, yb), (xb, ya), dxfattribs={"layer": layer})
            label = "TRÉMIE"
        else:
            label = f"{z['usage']} — Q={z['q']:g} kN/m²" if z.get("q") is not None else z["usage"]
        _text(msp, (xa + xb) / 2, (ya + yb) / 2 - 0.25, label, 0.11, layer)


def _column_section_at(res: ProjectResult, cid: str, storey: int):
    return next(r.design for r in res.columns if r.column_id == cid and r.storey == storey)


def _draw_columns(msp, res: ProjectResult, storey: int, label: bool = True, plan=None):
    for c in (plan or res.building).columns:
        d = _column_section_at(res, c.id, storey)
        x0, y0, x1, y1 = c.x - d.b / 2, c.y - d.h / 2, c.x + d.b / 2, c.y + d.h / 2
        _rect(msp, x0, y0, x1, y1, "POTEAUX")
        h = msp.add_hatch(color=8, dxfattribs={"layer": "POTEAUX"})
        h.paths.add_polyline_path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], is_closed=True)
        if label:
            _text(msp, x1 + 0.08, y1 + 0.12, f"{c.id} ({d.b * 100:.0f}x{d.h * 100:.0f})", 0.12,
                  align=TextEntityAlignment.BOTTOM_LEFT)


def plan_coffrage(res: ProjectResult, path: Path, level: str, storey: int, *, plan=None,
                  title: str | None = None) -> Path:
    """Plan de coffrage du plancher porté par les poteaux de l'étage `storey` (1 = bas)."""
    doc = _new_doc()
    msp = doc.modelspace()
    b = plan or res.building
    cols = b.column_map()
    _axes(msp, res, plan=b)
    _slab_outline(msp, b)
    _draw_columns(msp, res, storey, plan=b)
    _draw_zones(msp, b, roof=(level == "terrasse" or storey == res.project.n))
    for t in res.transfers:
        if t.storey != storey - 1:
            continue
        (_, _, xa, ya), (_, _, xb, yb) = [(a[0], a[1], a[2], a[3]) for a in
                                          next(tb.supports for tb in res.takedown.transfers if tb.id == t.beam_id)]
        w = t.design.b / 2
        if abs(yb - ya) < abs(xb - xa):
            for off in (-w, w):
                msp.add_line((xa, ya + off), (xb, ya + off), dxfattribs={"layer": "POUTRES", "color": 1})
            _text(msp, (xa + xb) / 2, ya - w - 0.15, f"{t.beam_id} ({t.design.b * 100:.0f}x{t.design.h * 100:.0f}) "
                  "TRANSFERT", 0.13, align=TextEntityAlignment.TOP_CENTER)
        else:
            for off in (-w, w):
                msp.add_line((xa + off, ya), (xa + off, yb), dxfattribs={"layer": "POUTRES", "color": 1})
            _text(msp, xa + w + 0.15, (ya + yb) / 2, f"{t.beam_id} ({t.design.b * 100:.0f}x{t.design.h * 100:.0f}) "
                  "TRANSFERT", 0.13, rot=90)
    proj = res.project
    # Poteaux de l'étage supérieur qui naissent sur ce plancher
    if not proj.single_plan and storey < proj.n:
        above = proj.storeys[storey].plan
        on_wall = {w.column_id for w in res.takedown.wall_supports if w.storey == storey}
        for c in above.columns:
            if c.id not in cols:
                x0, y0, x1, y1 = c.x - c.b / 2, c.y - c.h / 2, c.x + c.b / 2, c.y + c.h / 2
                _rect(msp, x0, y0, x1, y1, "POTEAUX")
                msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "POTEAUX", "color": 1})
                msp.add_line((x0, y1), (x1, y0), dxfattribs={"layer": "POTEAUX", "color": 1})
                tag = "sur mur" if c.id in on_wall else "naissant"
                _text(msp, x1 + 0.08, y0 - 0.12, f"{c.id} {tag}", 0.12, align=TextEntityAlignment.TOP_LEFT)
    designed = {r.beam_id: r.design for r in res.beams
                if (r.storey == storey - 1 if not proj.single_plan else r.level == level)}
    for bm in b.beams:
        c1, c2 = cols[bm.start], cols[bm.end]
        dz = designed.get(bm.id)
        sec_b, sec_h = (dz.b, dz.h) if dz else (bm.b, bm.h)
        sec = f"{sec_b * 100:.0f}x{sec_h * 100:.0f}" + (" TRANSFERT" if dz and any("transfert" in n for n in dz.notes) else "")
        w = sec_b / 2
        if bm.direction == "X":
            xa, xb = c1.x + c1.b / 2, c2.x - c2.b / 2
            msp.add_line((xa, c1.y - w), (xb, c1.y - w), dxfattribs={"layer": "POUTRES"})
            msp.add_line((xa, c1.y + w), (xb, c1.y + w), dxfattribs={"layer": "POUTRES"})
            _text(msp, (xa + xb) / 2, c1.y + w + 0.12, f"{bm.id} ({sec})", 0.12)
        else:
            ya, yb = c1.y + c1.h / 2, c2.y - c2.h / 2
            msp.add_line((c1.x - w, ya), (c1.x - w, yb), dxfattribs={"layer": "POUTRES"})
            msp.add_line((c1.x + w, ya), (c1.x + w, yb), dxfattribs={"layer": "POUTRES"})
            _text(msp, c1.x - w - 0.12, (ya + yb) / 2, f"{bm.id} ({sec})", 0.12, rot=90)
    ftype = res.loads.floor_type
    for p in b.panels:
        c = cols[p.corners[0]]
        cx, cy = c.x + p.lx / 2, c.y + p.ly / 2
        if ftype == "corps_creux" or min(p.lx, p.ly) / max(p.lx, p.ly) < 0.4:
            # Flèche du sens porteur des poutrelles (portée = petit côté)
            if p.lx <= p.ly:
                msp.add_line((cx - p.lx / 2 + 0.3, cy), (cx + p.lx / 2 - 0.3, cy), dxfattribs={"layer": "TEXTE"})
                for s in (-1, 1):
                    tip = cx + s * (p.lx / 2 - 0.3)
                    msp.add_line((tip, cy), (tip - s * 0.2, cy + 0.1), dxfattribs={"layer": "TEXTE"})
                    msp.add_line((tip, cy), (tip - s * 0.2, cy - 0.1), dxfattribs={"layer": "TEXTE"})
            else:
                msp.add_line((cx, cy - p.ly / 2 + 0.3), (cx, cy + p.ly / 2 - 0.3), dxfattribs={"layer": "TEXTE"})
                for s in (-1, 1):
                    tip = cy + s * (p.ly / 2 - 0.3)
                    msp.add_line((cx, tip), (cx + 0.1, tip - s * 0.2), dxfattribs={"layer": "TEXTE"})
                    msp.add_line((cx, tip), (cx - 0.1, tip - s * 0.2), dxfattribs={"layer": "TEXTE"})
            txt = "Plancher corps creux" if ftype == "corps_creux" else "Dalle pleine (1 sens)"
        else:
            txt = "Dalle pleine (2 sens)"
        _text(msp, cx, cy + 0.35, f"{p.id} — {txt}", 0.12)
    title = title or ("PLAN DE COFFRAGE — " + ("TERRASSE" if level == "terrasse" else "ÉTAGE COURANT"))
    _cartouche(msp, (max(b.grid_x) if b.grid_x else 0) - 5.5, (min(b.grid_y) if b.grid_y else 0) - 4.5, title, res)
    doc.saveas(path)
    return path


def plan_fondations(res: ProjectResult, path: Path, types: dict[str, str]) -> Path:
    doc = _new_doc()
    msp = doc.modelspace()
    b = res.base_plan
    _axes(msp, res, ext=2.0, plan=b)
    for ft in res.footings:
        f = ft.design
        x, y = ft.x, ft.y
        _rect(msp, x - f.A / 2, y - f.B / 2, x + f.A / 2, y + f.B / 2, "SEMELLES")
        tag = " (sous mur)" if ft.on_wall else ""
        _text(msp, x, y - f.B / 2 - 0.15, f"{types.get(ft.column_id, '')} {f.A * 100:.0f}x{f.B * 100:.0f} "
              f"h={f.h * 100:.0f}{tag}", 0.12, align=TextEntityAlignment.TOP_CENTER)
    if res.raft:
        _slab_outline(msp, type("P", (), {"slab": b.footprint or b.slab})(), "SEMELLES")
        _text(msp, (max(b.grid_x) + min(b.grid_x)) / 2 if b.grid_x else 0, (min(b.grid_y) if b.grid_y else 0) - 1.0,
              f"RADIER GÉNÉRAL ép. {res.raft['epaisseur'] * 100:.0f} cm — {res.raft['aciers']} (2 nappes, 2 directions)",
              0.2, "SEMELLES")
    for p_ in res.piles:
        n = p_["n_pieux"] or 1
        for k in range(n):
            ang = 2 * math.pi * k / n
            r0 = 0.0 if n == 1 else 0.6
            msp.add_circle((p_["x"] + r0 * math.cos(ang), p_["y"] + r0 * math.sin(ang)), 0.25,
                           dxfattribs={"layer": "SEMELLES"})
        _text(msp, p_["x"], p_["y"] - 1.0, f"{p_['poteau']} : {p_['n_pieux'] or '?'} pieu(x) — Nser {p_['nser']:.0f} kN",
              0.12, "SEMELLES")
    _draw_columns(msp, res, 1, label=False, plan=b)
    title = {"pieux": "PLAN DE FONDATIONS — PIEUX", "radier": "PLAN DE FONDATIONS — RADIER"}.get(
        res.foundation_type, "PLAN DE FONDATIONS — SEMELLES")
    _cartouche(msp, (max(b.grid_x) if b.grid_x else 0) - 5.5, (min(b.grid_y) if b.grid_y else 0) - 5.0,
               title, res,
               f"Règlement : {res.code.name} — σsol = {res.sigma_sol:g} MPa")
    doc.saveas(path)
    return path


# ---------------------------------------------------------------------------- ferraillage
@dataclass
class ElementType:
    name: str
    key: tuple
    members: list[str] = field(default_factory=list)
    data: object = None


def group_types(res: ProjectResult) -> tuple[list[ElementType], list[ElementType], list[ElementType]]:
    col_types: dict[tuple, ElementType] = {}
    for r in sorted(res.columns, key=lambda r: (r.storey, int(r.column_id[1:]))):
        d = r.design
        key = (d.b, d.h, str(d.bars), str(d.stirrups))
        t = col_types.setdefault(key, ElementType(f"PT{len(col_types) + 1}", key, data=d))
        t.members.append(f"{r.column_id}/{r.storey_name or 'N' + str(r.storey)}")
    beam_types: dict[tuple, ElementType] = {}
    from ..design import BeamResult

    extra = [BeamResult(t.beam_id, t.floor, t.length, 8 * t.m0 / t.length ** 2, t.m0, t.design, t.storey)
             for t in res.transfers]
    for r in list(res.beams) + extra:
        d = r.design
        key = (d.b, d.h, round(r.span, 2), str(d.bars_bottom), str(d.bars_top), str(d.stirrups))
        t = beam_types.setdefault(key, ElementType(f"PO{len(beam_types) + 1}", key, data=r))
        t.members.append(f"{r.beam_id}/{r.level}")
    foot_types: dict[tuple, ElementType] = {}
    for f in res.footings:
        d = f.design
        key = (d.A, d.B, d.h, str(d.bars_x), str(d.bars_y))
        t = foot_types.setdefault(key, ElementType(f"S{len(foot_types) + 1}", key, data=d))
        t.members.append(f.column_id)
    return list(col_types.values()), list(beam_types.values()), list(foot_types.values())


def _bar_positions(b: float, h: float, cover: float, bars: Bars) -> list[tuple[float, float]]:
    """Répartit n barres sur le périmètre d'une section b×h (barres d'angle d'abord)."""
    x0, y0, x1, y1 = -b / 2 + cover, -h / 2 + cover, b / 2 - cover, h / 2 - cover
    n = bars.n
    extra = n - 4
    # Répartition proportionnelle aux longueurs des côtés
    total = (x1 - x0) + (y1 - y0)
    nx = round(extra / 2 * (x1 - x0) / total) if total else 0
    ny = extra // 2 - nx
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for k in range(1, nx + 1):
        x = x0 + k * (x1 - x0) / (nx + 1)
        pts += [(x, y0), (x, y1)]
    for k in range(1, ny + 1):
        y = y0 + k * (y1 - y0) / (ny + 1)
        pts += [(x0, y), (x1, y)]
    return pts


def plan_ferraillage(res: ProjectResult, path: Path, col_t, beam_t, foot_t) -> Path:
    doc = _new_doc()
    msp = doc.modelspace()
    cover = res.code.cover
    S = 4.0  # agrandissement des détails de section
    y = 0.0
    _text(msp, 0, y + 1.2, "FERRAILLAGE DES POTEAUX (sections à l'échelle x4)", 0.25,
          align=TextEntityAlignment.BOTTOM_LEFT)
    x = 1.0
    for t in col_t:
        d = t.data
        bw, bh = d.b * S, d.h * S
        _rect(msp, x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2, "COFFRAGE")
        c = (cover - 0.005) * S
        _rect(msp, x - bw / 2 + c, y - bh / 2 + c, x + bw / 2 - c, y + bh / 2 - c, "CADRES")
        if d.bars:
            for px, py in _bar_positions(d.b, d.h, cover + 0.01, d.bars):
                msp.add_circle((x + px * S, y + py * S), d.bars.d / 2000 * S, dxfattribs={"layer": "ACIERS"})
        _text(msp, x, y - bh / 2 - 0.25, f"{t.name} : {d.b * 100:.0f}x{d.h * 100:.0f}", 0.15)
        _text(msp, x, y - bh / 2 - 0.50, f"{d.bars} — {d.stirrups}", 0.12)
        _text(msp, x, y - bh / 2 - 0.72, f"({len(t.members)} tronçon(s))", 0.10)
        x += max(bw, 2.4) + 0.8

    y -= 4.0
    _text(msp, 0, y + 1.0, "FERRAILLAGE DES POUTRES (élévation et coupe)", 0.25,
          align=TextEntityAlignment.BOTTOM_LEFT)
    for t in beam_t:
        r = t.data
        d = r.design
        L, h = r.span, d.h
        _rect(msp, 0, y - h, L, y, "COFFRAGE")
        c = cover + 0.01
        msp.add_line((c - 0.1, y - h + c), (L - c + 0.1, y - h + c), dxfattribs={"layer": "ACIERS"})
        msp.add_line((c - 0.1, y - c), (L - c + 0.1, y - c), dxfattribs={"layer": "ACIERS"})
        if d.stirrups:
            n = max(2, int(L / d.stirrups.s) + 1)
            for k in range(n):
                xs = 0.05 + k * (L - 0.10) / (n - 1)
                msp.add_line((xs, y - h + cover), (xs, y - cover), dxfattribs={"layer": "CADRES"})
        _text(msp, L / 2, y + 0.12, f"{t.name} — {d.b * 100:.0f}x{d.h * 100:.0f} — L = {L:.2f} m ({r.level})",
              0.14, align=TextEntityAlignment.BOTTOM_CENTER)
        _text(msp, L / 2, y - h - 0.12, f"Inf. : {d.bars_bottom}   Sup. : {d.bars_top}   {d.stirrups}",
              0.11, align=TextEntityAlignment.TOP_CENTER)
        # Coupe transversale à l'échelle x4 à droite
        cx = L + 1.5
        bw, bh = d.b * S, d.h * S
        _rect(msp, cx - bw / 2, y - bh, cx + bw / 2, y, "COFFRAGE")
        cc = cover * S
        _rect(msp, cx - bw / 2 + cc, y - bh + cc, cx + bw / 2 - cc, y - cc, "CADRES")
        for bars, top in ((d.bars_bottom, False), (d.bars_top, True)):
            if not bars:
                continue
            per_row = max(2, math.floor((d.b - 2 * cover - 0.016) / 0.045) + 1)
            for k in range(bars.n):
                row, pos = divmod(k, per_row)
                in_row = min(per_row, bars.n - row * per_row)
                span_w = bw - 2 * (cc + 0.01 * S)
                px = cx - span_w / 2 + (pos * span_w / (in_row - 1) if in_row > 1 else span_w / 2)
                off = (cover + 0.01 + row * 0.04) * S
                py = y - off if top else y - bh + off
                msp.add_circle((px, py), bars.d / 2000 * S, dxfattribs={"layer": "ACIERS"})
        y -= max(h, bh) + 1.2

    y -= 1.0
    _text(msp, 0, y + 1.0, "FERRAILLAGE DES SEMELLES (vue en plan)", 0.25, align=TextEntityAlignment.BOTTOM_LEFT)
    x = 0.0
    for t in foot_t:
        d = t.data
        _rect(msp, x, y - d.B, x + d.A, y, "COFFRAGE")
        c = 0.05
        if d.bars_x:
            for k in range(d.bars_x.n):
                yy = y - d.B + c + k * (d.B - 2 * c) / max(1, d.bars_x.n - 1)
                msp.add_line((x + c, yy), (x + d.A - c, yy), dxfattribs={"layer": "ACIERS"})
        if d.bars_y:
            for k in range(d.bars_y.n):
                xx = x + c + k * (d.A - 2 * c) / max(1, d.bars_y.n - 1)
                msp.add_line((xx, y - d.B + c), (xx, y - c), dxfattribs={"layer": "ACIERS"})
        _text(msp, x + d.A / 2, y - d.B - 0.15, f"{t.name} : {d.A * 100:.0f}x{d.B * 100:.0f} h={d.h * 100:.0f}",
              0.14, align=TextEntityAlignment.TOP_CENTER)
        _text(msp, x + d.A / 2, y - d.B - 0.40, f"// A : {d.bars_x}   // B : {d.bars_y}", 0.11,
              align=TextEntityAlignment.TOP_CENTER)
        _text(msp, x + d.A / 2, y - d.B - 0.62, ", ".join(t.members), 0.10, align=TextEntityAlignment.TOP_CENTER)
        x += d.A + 1.5
    # Escaliers : coupe sur la volée (échelle 1)
    if res.stairs:
        y -= 3.0
        _text(msp, 0, y + 1.0, "ESCALIERS (coupe sur volée)", 0.25, align=TextEntityAlignment.BOTTOM_LEFT)
        x = 0.0
        for st in res.stairs:
            n_f = math.ceil(st.risers / st.flights)
            pts = [(x, y - n_f * st.riser_h)]
            cx, cy = x, y - n_f * st.riser_h
            for k in range(n_f):
                cy += st.riser_h
                pts.append((cx, cy))
                if k < n_f - 1:
                    cx += st.going
                    pts.append((cx, cy))
            pts.append((cx + st.landing, cy))
            msp.add_lwpolyline(pts, dxfattribs={"layer": "COFFRAGE"})
            # sous-face de paillasse et de palier
            e_ = st.thickness / math.cos(math.radians(st.angle))
            x0b, y0b = x, y - n_f * st.riser_h - e_
            x1b, y1b = x + st.flight_len, y - st.riser_h - e_
            msp.add_line((x0b, y0b), (x1b, y1b + st.riser_h), dxfattribs={"layer": "COFFRAGE"})
            msp.add_line((x1b, y1b + st.riser_h), (cx + st.landing, cy - st.thickness),
                         dxfattribs={"layer": "COFFRAGE"})
            c = 0.03
            msp.add_line((x0b + 0.05, y0b + c), (x1b, y1b + st.riser_h + c), dxfattribs={"layer": "ACIERS"})
            msp.add_line((x1b, y1b + st.riser_h + c), (cx + st.landing - 0.05, cy - st.thickness + c),
                         dxfattribs={"layer": "ACIERS"})
            _text(msp, x + (st.flight_len + st.landing) / 2, y - n_f * st.riser_h - 0.6,
                  f"{st.floor} — {st.risers} marches {st.riser_h * 100:.1f}×{st.going * 100:.0f} — paillasse "
                  f"{st.thickness * 100:.0f} cm", 0.12, align=TextEntityAlignment.TOP_CENTER)
            _text(msp, x + (st.flight_len + st.landing) / 2, y - n_f * st.riser_h - 0.85,
                  f"Inf. {st.bars_bottom} — Chapeaux {st.bars_top} — Répartition {st.bars_dist}", 0.11,
                  align=TextEntityAlignment.TOP_CENTER)
            x += st.flight_len + st.landing + 1.5
        y -= 3.0
    _cartouche(msp, 0, y - 4.5, "PLANS DE FERRAILLAGE", res)
    doc.saveas(path)
    return path


def plan_controle(bld, drawing, path: Path) -> Path:
    """Plan de contrôle : géométrie importée (gris) + modèle reconnu (couleur)."""
    doc = _new_doc()
    doc.layers.add("IMPORT", color=8)
    doc.layers.add("MODELE", color=1)
    msp = doc.modelspace()
    ox, oy = bld.origin  # la reconnaissance a ramené l'origine sur le premier poteau
    _slab_outline(msp, bld, "MODELE")
    for r in drawing.rects:
        _rect(msp, r.x0 - ox, r.y0 - oy, r.x1 - ox, r.y1 - oy, "IMPORT")
    for s in drawing.segments:
        msp.add_line((s.x0 - ox, s.y0 - oy), (s.x1 - ox, s.y1 - oy), dxfattribs={"layer": "IMPORT"})
    cols = bld.column_map()
    for c in bld.columns:
        _rect(msp, c.x - c.b / 2, c.y - c.h / 2, c.x + c.b / 2, c.y + c.h / 2, "MODELE")
        _text(msp, c.x, c.y + c.h / 2 + 0.15, c.id, 0.15, "MODELE")
    for bm in bld.beams:
        a, b = cols[bm.start], cols[bm.end]
        msp.add_line((a.x, a.y), (b.x, b.y), dxfattribs={"layer": "MODELE"})
        _text(msp, (a.x + b.x) / 2, (a.y + b.y) / 2 + 0.12, bm.id, 0.12, "MODELE")
    doc.saveas(path)
    return path
