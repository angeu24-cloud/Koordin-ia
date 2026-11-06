"""Plans DXF des réseaux : plomberie, électricité, climatisation (un fichier par lot,
niveaux côte à côte, avec schéma de colonnes ou schéma unifilaire)."""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..slab import SlabMask, outline_segments
from .design import MEPResult

LAYERS = {"FOND": 8, "TEXTE": 7, "PL-EF": 5, "PL-EU": 30, "PL-APP": 4, "EL-ECL": 2, "EL-PC": 1, "EL-INT": 6,
          "EL-TD": 3, "CL-UNITE": 4, "CL-LIAISON": 140, "SCHEMA": 7}


def _doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for n, c in LAYERS.items():
        doc.layers.add(n, color=c)
    return doc


def _t(msp, x, y, s, h=0.15, layer="TEXTE", align=TextEntityAlignment.MIDDLE_CENTER):
    e = msp.add_text(str(s), height=h, dxfattribs={"layer": layer})
    e.set_placement((x, y), align=align)


def _background(msp, plan, dx: float, title: str):
    fp = plan.footprint or plan.slab
    if fp:
        for x0, y0, x1, y1 in outline_segments(SlabMask.from_dict(fp)):
            msp.add_line((x0 + dx, y0), (x1 + dx, y1), dxfattribs={"layer": "FOND"})
    for x0, y0, x1, y1, t in plan.walls:
        if abs(y1 - y0) < 1e-6:
            msp.add_lwpolyline([(x0 + dx, y0 - t / 2), (x1 + dx, y0 - t / 2), (x1 + dx, y0 + t / 2),
                                (x0 + dx, y0 + t / 2)], close=True, dxfattribs={"layer": "FOND"})
        else:
            msp.add_lwpolyline([(x0 - t / 2 + dx, y0), (x0 + t / 2 + dx, y0), (x0 + t / 2 + dx, y1),
                                (x0 - t / 2 + dx, y1)], close=True, dxfattribs={"layer": "FOND"})
    xs = [c.x for c in plan.columns] or [0]
    ys = [c.y for c in plan.columns] or [0]
    _t(msp, dx + (min(xs) + max(xs)) / 2, max(ys) + 3.0, title, 0.45)


def _extent(plan) -> float:
    xs = [c.x for c in plan.columns] or [0, 10]
    return max(xs) - min(xs) + 12.0


def write_mep_drawings(project, mep: MEPResult, folder: Path) -> list[Path]:
    storeys = project.storeys[:1] if project.single_plan else project.storeys
    paths = []
    # ------------------------------------------------------------------ plomberie
    doc = _doc()
    msp = doc.modelspace()
    dx = 0.0
    sym = {"wc": "WC", "lavabo": "L", "douche": "D", "evier": "E", "urinoir": "U"}
    for st, sm in zip(storeys, mep.storeys):
        _background(msp, st.plan, dx, f"PLOMBERIE — {sm.name}")
        for g in sm.groups:
            gx, gy = g["x"] + dx, g["y"]
            msp.add_lwpolyline([(gx - .3, gy - .3), (gx + .3, gy - .3), (gx + .3, gy + .3), (gx - .3, gy + .3)], close=True,
                               dxfattribs={"layer": "PL-EF"})
            _t(msp, gx, gy + .55, f"{g['colonne']} EF Ø{g['dn_alimentation']} / EV Ø{g['dn_chute']}", .14, "PL-EF")
        for f in sm.fixtures:
            fx, fy = f["x"] + dx, f["y"]
            msp.add_circle((fx, fy), .22, dxfattribs={"layer": "PL-APP"})
            _t(msp, fx, fy, sym[f["type"]], .12, "PL-APP")
            g = min(sm.groups, key=lambda g: abs(g["x"] - f["x"]) + abs(g["y"] - f["y"])) if sm.groups else None
            if g:
                msp.add_lwpolyline([(fx, fy), (g["x"] + dx, fy), (g["x"] + dx, g["y"])], dxfattribs={"layer": "PL-EF"})
                msp.add_lwpolyline([(fx, fy - .1), (g["x"] + dx + .1, fy - .1), (g["x"] + dx + .1, g["y"])],
                                   dxfattribs={"layer": "PL-EU"})
        dx += _extent(st.plan)
    # schéma des colonnes
    x0, y0 = dx + 2, 0.0
    _t(msp, x0 + 3, y0 + 2 + 3.2 * len(storeys), "SCHÉMA DES COLONNES MONTANTES", .4, "SCHEMA")
    for ci, col in enumerate(mep.columns):
        cx = x0 + 4 * ci
        _t(msp, cx, y0 - .6, col["id"], .25, "SCHEMA")
        for k, seg in enumerate(col.get("segments", [])):
            ya, yb = y0 + 3.2 * k, y0 + 3.2 * (k + 1)
            msp.add_line((cx, ya), (cx, yb), dxfattribs={"layer": "PL-EF"})
            msp.add_line((cx + .4, ya), (cx + .4, yb), dxfattribs={"layer": "PL-EU"})
            _t(msp, cx + .6, ya + 1.6, f"{seg['niveau']} : EF Ø{seg['dn']} — {seg['appareils']} app. — chute Ø{seg['chute_dn']}",
               .14, "SCHEMA", TextEntityAlignment.MIDDLE_LEFT)
    p = folder / "reseau_plomberie.dxf"
    doc.saveas(p)
    paths.append(p)
    # ------------------------------------------------------------------ électricité
    doc = _doc()
    msp = doc.modelspace()
    dx = 0.0
    for st, sm in zip(storeys, mep.storeys):
        _background(msp, st.plan, dx, f"ÉLECTRICITÉ — {sm.name}")
        for x, y, kind in sm.lights:
            msp.add_circle((x + dx, y), .18, dxfattribs={"layer": "EL-ECL"})
            msp.add_line((x + dx - .13, y - .13), (x + dx + .13, y + .13), dxfattribs={"layer": "EL-ECL"})
            msp.add_line((x + dx - .13, y + .13), (x + dx + .13, y - .13), dxfattribs={"layer": "EL-ECL"})
        for x, y, wet in sm.sockets:
            msp.add_arc((x + dx, y), .14, 0, 180, dxfattribs={"layer": "EL-PC"})
            msp.add_line((x + dx - .14, y), (x + dx + .14, y), dxfattribs={"layer": "EL-PC"})
        for x, y in sm.switches:
            msp.add_circle((x + dx, y), .08, dxfattribs={"layer": "EL-INT"})
            msp.add_line((x + dx, y), (x + dx + .2, y + .2), dxfattribs={"layer": "EL-INT"})
        tx, ty = sm.td
        msp.add_lwpolyline([(tx + dx - .4, ty - .25), (tx + dx + .4, ty - .25), (tx + dx + .4, ty + .25),
                            (tx + dx - .4, ty + .25)], close=True, dxfattribs={"layer": "EL-TD"})
        _t(msp, tx + dx, ty, "TD", .2, "EL-TD")
        _t(msp, tx + dx, ty - .55, f"{sm.power_kw:.1f} kW — {sm.current_a:.0f} A", .14, "EL-TD")
        dx += _extent(st.plan)
    # schéma unifilaire
    x0 = dx + 2
    _t(msp, x0 + 4, 3.5 + 2.2 * len(mep.storeys), "SCHÉMA UNIFILAIRE", .4, "SCHEMA")
    msp.add_lwpolyline([(x0, 0), (x0 + 3, 0), (x0 + 3, 1.2), (x0, 1.2)], close=True, dxfattribs={"layer": "SCHEMA"})
    _t(msp, x0 + 1.5, .8, "TGBT", .25, "SCHEMA")
    _t(msp, x0 + 1.5, .35, f"{mep.tgbt['puissance_kva']} kVA — {mep.tgbt['courant_a']:.0f} A", .14, "SCHEMA")
    for k, sm in enumerate(mep.storeys):
        y = 2.2 * (k + 1)
        msp.add_line((x0 + 3, .6), (x0 + 5, y + .4), dxfattribs={"layer": "SCHEMA"})
        msp.add_lwpolyline([(x0 + 5, y), (x0 + 7, y), (x0 + 7, y + .8), (x0 + 5, y + .8)], close=True,
                           dxfattribs={"layer": "SCHEMA"})
        _t(msp, x0 + 6, y + .4, f"TD {sm.name}", .14, "SCHEMA")
        c = sm.circuits
        _t(msp, x0 + 7.3, y + .55, f"Câble {sm.feeder['section_mm2']} mm² — {sm.feeder['longueur_m']} m — "
           f"ΔU {sm.feeder['chute_tension']} %", .13, "SCHEMA", TextEntityAlignment.MIDDLE_LEFT)
        _t(msp, x0 + 7.3, y + .2, f"{c['eclairage']} circ. éclairage 15 A (1,5 mm²) — {c['prises']} circ. prises 20 A "
           f"(2,5 mm²) — {c['clim']} circ. clim 20 A — différentiels 30 mA", .12, "SCHEMA", TextEntityAlignment.MIDDLE_LEFT)
    p = folder / "reseau_electricite.dxf"
    doc.saveas(p)
    paths.append(p)
    # ------------------------------------------------------------------ climatisation
    doc = _doc()
    msp = doc.modelspace()
    dx = 0.0
    for st, sm in zip(storeys, mep.storeys):
        _background(msp, st.plan, dx, f"CLIMATISATION — {sm.name} ({sm.cool_kw:.0f} kW)")
        for u in sm.units:
            x, y = u["x"] + dx, u["y"]
            msp.add_lwpolyline([(x - .45, y - .12), (x + .45, y - .12), (x + .45, y + .12), (x - .45, y + .12)],
                               close=True, dxfattribs={"layer": "CL-UNITE"})
            _t(msp, x, y + .3, f"Split {u['cv']:g} CV ({u['kw']:g} kW)", .12, "CL-UNITE")
            msp.add_line((x, y), (x, y - .8), dxfattribs={"layer": "CL-LIAISON"})
        dx += _extent(st.plan)
    p = folder / "reseau_climatisation.dxf"
    doc.saveas(p)
    paths.append(p)
    return paths
