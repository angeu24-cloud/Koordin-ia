"""Plans d'exécution d'un mur de soutènement cantilever : jeu de planches A3 (DXF + PDF).

Planche 1 : vue en plan et élévation de chaque mur (joints, barbacanes, repère de coupe) — 1/100.
Planche 2 : coupe type de coffrage (cotes, niveaux, drainage) et détails (joint, barbacane) — 1/20 et 1/10.
Planche 3 : coupe type de ferraillage (repères des barres) et nomenclature des aciers — 1/20.

Les planches sont dessinées en millimètres papier (une unité = 1 mm sur la feuille A3) ; chaque vue a
sa propre échelle et ses cotes affichent les longueurs réelles en mètres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .codes.common import bar_mass
from .soutenement import WallResult

A3 = (420.0, 297.0)
MARGIN = 10.0
LAYERS = {"CADRE": 7, "BETON": 7, "BETON_HACH": 9, "TERRE": 8, "ACIERS": 1, "COTES": 3, "TEXTES": 7,
          "AXES": 4, "DRAINAGE": 5, "CACHE": 8}
AL = TextEntityAlignment


@dataclass
class View:
    """Transformation mètres réels → millimètres papier pour une vue à l'échelle 1/scale."""
    x0: float
    y0: float
    scale: float

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (self.x0 + x * 1000 / self.scale, self.y0 + y * 1000 / self.scale)

    def k(self, d: float) -> float:
        return d * 1000 / self.scale


# ------------------------------------------------------------------ découpage et nomenclature
def segments(length: float, max_len: float = 10.0) -> list[float]:
    """Plots entre joints de dilatation (≤ max_len), de longueurs égales."""
    n = max(1, math.ceil(length / max_len - 1e-9))
    return [round(length / n, 3)] * n


def _parse(bars: str) -> tuple[int, float]:
    """« HA10 e=25 cm » → (10, 0.25)."""
    d = int(bars.split()[0][2:])
    e = float(bars.split("=")[1].split()[0].replace(",", ".")) / 100
    return d, e


def _count(span: float, e: float, end: float = 0.05) -> int:
    return int(math.floor((span - 2 * end) / e + 1e-9)) + 1


def bar_layout(res: WallResult) -> dict:
    """Barres de la coupe type : formes (polylignes dans la coupe, m) et barres filantes (points)."""
    g, w, ra = res.geometry, res.wall, res.reinforcement
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd, kw = g.get("key_depth", 0.0), g.get("key_width", 0.0)
    c = w["cover"]
    B = toe + tb + heel
    xb = toe + tb - c                                  # nu des aciers côté terres
    ytop = hb + H - c
    d1, e1 = ra["voile"]["d_mm"], ra["voile"]["e_m"]
    dT, eT = ra["talon"]["d_mm"], ra["talon"]["e_m"]
    dP, eP = ra["patin"]["d_mm"], ra["patin"]["e_m"]
    dRv, eRv = _parse(ra["voile"]["repartition"])
    dRt, eRt = _parse(ra["talon"]["repartition"])
    dRp, eRp = _parse(ra["patin"]["repartition"])
    shapes = []                                        # barres transversales (forme dans la coupe)
    if kd > 0:
        ybot = -kd + c
        r1 = [(xb - (kw - 2 * c), ybot), (xb, ybot), (xb, ytop)]
    else:
        ybot = c + 0.012
        r1 = [(xb - 0.50, ybot), (xb, ybot), (xb, ytop)]
    shapes.append(dict(rep=1, nom="Voile, face côté terres (porteur)", d=d1, e=e1, path=r1))
    xf0, xf1 = toe + c, toe + tb - tt + c              # face avant inclinée (fruit)
    shapes.append(dict(rep=2, nom="Voile, face avant (verticales)", d=8, e=0.20,
                       path=[(xf0 - 0.30, c + 0.012), (xf0, c + 0.012), (xf1, ytop)]))
    shapes.append(dict(rep=5, nom="Semelle, nappe supérieure (talon)", d=dT, e=eT,
                       path=[(c, c + 0.03), (c, hb - c), (B - c, hb - c), (B - c, c + 0.03)]))
    shapes.append(dict(rep=6, nom="Semelle, nappe inférieure (patin)", d=dP, e=eP,
                       path=[(c + 0.015, hb - c - 0.03), (c + 0.015, c), (B - c - 0.015, c), (B - c - 0.015, hb - c - 0.03)]))
    x_t0, x_t1 = toe + tb - tt, toe + tb
    shapes.append(dict(rep=9, nom="Épingles de tête du voile", d=8, e=0.20,
                       path=[(x_t0 + c, ytop - 0.30), (x_t0 + c, ytop), (x_t1 - c, ytop), (x_t1 - c, ytop - 0.30)]))
    if kd > 0:
        xk0, xk1 = toe + tb - kw, toe + tb
        shapes.append(dict(rep=10, nom="Bêche, cadres en U", d=10, e=0.20,
                           path=[(xk0 + c + 0.015, hb - c - 0.02), (xk0 + c + 0.015, -kd + c + 0.015),
                                 (xk1 - c - 0.015, -kd + c + 0.015), (xk1 - c - 0.015, hb - c - 0.02)]))
    # barres filantes (points dans la coupe)
    lines = []
    ys = [hb + 0.10 + i * eRv for i in range(int((H - 0.15) / eRv) + 1)]
    lines.append(dict(rep=3, nom="Voile, répartition côté terres", d=dRv, e=eRv,
                      pts=[(xb - 0.006 - d1 / 1000, y) for y in ys]))
    ys8 = [hb + 0.10 + i * 0.20 for i in range(int((H - 0.15) / 0.20) + 1)]
    lines.append(dict(rep=4, nom="Voile, face avant (horizontales)", d=8, e=0.20,
                      pts=[(toe + (tb - tt) * (y - hb) / H + c + 0.010, y) for y in ys8]))
    n7 = _count(B, eRt)
    lines.append(dict(rep=7, nom="Semelle, répartition nappe supérieure", d=dRt, e=eRt,
                      pts=[(c + 0.03 + i * (B - 2 * c - 0.06) / (n7 - 1), hb - c - 0.012) for i in range(n7)]))
    n8 = _count(B, eRp)
    lines.append(dict(rep=8, nom="Semelle, répartition nappe inférieure", d=dRp, e=eRp,
                      pts=[(c + 0.045 + i * (B - 2 * c - 0.09) / (n8 - 1), c + 0.012) for i in range(n8)]))
    if kd > 0:
        xk0, xk1 = toe + tb - kw, toe + tb
        lines.append(dict(rep=11, nom="Bêche, filants", d=10, e=0.0,
                          pts=[(xk0 + c + 0.03, -kd + c + 0.03), (xk1 - c - 0.03, -kd + c + 0.03),
                               (xk0 + c + 0.03, -kd / 2), (xk1 - c - 0.03, -kd / 2)]))
    return {"shapes": shapes, "lines": lines}


def _length(path) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def bar_schedule(res: WallResult, walls: list[tuple[str, float]]) -> dict:
    """Nomenclature : une ligne par repère, nombre de barres par mur (plots entre joints)."""
    lay = bar_layout(res)
    c = res.wall["cover"]
    rows = []
    for s in lay["shapes"]:
        L = _length(s["path"])
        nb = [sum(_count(Ls, s["e"]) for Ls in segments(Lw)) for _, Lw in walls]
        rows.append(dict(rep=s["rep"], nom=s["nom"], d=s["d"], e=s["e"], L=round(L, 2), nb=nb, path=s["path"]))
    for ln in lay["lines"]:
        per_seg = len(ln["pts"])
        nb, Lbar = [], None
        for _, Lw in walls:
            segs = segments(Lw)
            nb.append(per_seg * len(segs))
            Lbar = segs[0] - 2 * c
        # mêmes plots pour tous les murs d'une même longueur ; si les longueurs diffèrent, une ligne par mur
        rows.append(dict(rep=ln["rep"], nom=ln["nom"], d=ln["d"], e=ln["e"], L=None, nb=nb, per_seg=per_seg,
                         seg_len=[segments(Lw)[0] - 2 * c for _, Lw in walls], path=None))
    for r in rows:
        if r["L"] is not None:
            r["L_tot"] = [round(r["L"] * n, 2) for n in r["nb"]]
        else:
            r["L_tot"] = [round(Ls * n, 2) for Ls, n in zip(r["seg_len"], r["nb"])]
        r["kg"] = [round(lt * bar_mass(r["d"]), 1) for lt in r["L_tot"]]
    rows.sort(key=lambda r: r["rep"])
    by_d: dict[int, float] = {}
    for r in rows:
        by_d[r["d"]] = by_d.get(r["d"], 0.0) + sum(r["kg"])
    total = sum(by_d.values())
    return {"rows": rows, "par_diametre_kg": {k: round(v, 1) for k, v in sorted(by_d.items())},
            "total_kg": round(total, 1), "par_mur_kg": [round(sum(r["kg"][i] for r in rows), 1) for i in range(len(walls))],
            "walls": walls}


# ------------------------------------------------------------------ primitives de dessin
def _doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4                       # millimètres (papier)
    doc.header["$LTSCALE"] = 1.0
    for name, col in LAYERS.items():
        doc.layers.add(name, color=col)
    doc.layers.get("AXES").dxf.linetype = "CENTER"
    doc.layers.get("CACHE").dxf.linetype = "DASHED"
    doc.styles.add("BATI", font="DejaVuSans.ttf")
    return doc


def _t(m, txt, x, y, h=2.5, al=AL.BOTTOM_LEFT, layer="TEXTES", rot=0.0):
    t = m.add_text(txt, height=h, rotation=rot, dxfattribs={"layer": layer, "style": "BATI"})
    t.set_placement((x, y), align=al)
    return t


def _pl(m, pts, layer, close=False, width=0.0):
    e = m.add_lwpolyline(pts, close=close, dxfattribs={"layer": layer})
    if width:
        e.dxf.const_width = width
    return e


def _dim(m, v: View, p1, p2, base, vertical=False, txt_h=2.2):
    """Cote entre deux points réels (m) ; base = position réelle de la ligne de cote."""
    a, b, bs = v.p(*p1), v.p(*p2), v.p(*base)
    d = m.add_linear_dim(base=bs, p1=a, p2=b, angle=90 if vertical else 0, dxfattribs={"layer": "COTES"},
                         override={"dimtxt": txt_h, "dimasz": 1.8, "dimexe": 1.0, "dimexo": 1.0, "dimgap": 0.8,
                                   "dimdec": 2, "dimzin": 0, "dimdsep": ord(","), "dimlfac": v.scale / 1000,
                                   "dimtad": 1, "dimtxsty": "BATI", "dimtih": 0, "dimtoh": 0})
    d.render()


def _hatch_solid(m, pts, color=9, layer="BETON_HACH"):
    h = m.add_hatch(color=color, dxfattribs={"layer": layer})
    h.paths.add_polyline_path(pts, is_closed=True)
    return h


def _hatch_earth(m, pts, scale=0.6):
    h = m.add_hatch(color=252, dxfattribs={"layer": "TERRE", "lineweight": 0})
    h.set_pattern_fill("EARTH", scale=scale * 1.6)
    h.paths.add_polyline_path(pts, is_closed=True)
    return h


def _frame(m, title: str, scale_txt: str, sheet: int, n_sheets: int, info: dict):
    W, Hh = A3
    _pl(m, [(0, 0), (W, 0), (W, Hh), (0, Hh)], "CADRE", close=True)
    _pl(m, [(MARGIN, MARGIN / 2), (W - MARGIN / 2, MARGIN / 2), (W - MARGIN / 2, Hh - MARGIN / 2),
            (MARGIN, Hh - MARGIN / 2)], "CADRE", close=True, width=0.5)
    # cartouche
    cw, ch = 170.0, 38.0
    x0, y0 = W - MARGIN / 2 - cw, MARGIN / 2
    _pl(m, [(x0, y0), (x0 + cw, y0), (x0 + cw, y0 + ch), (x0, y0 + ch)], "CADRE", close=True, width=0.35)
    for yy in (y0 + 10, y0 + 20, y0 + 30):
        m.add_line((x0, yy), (x0 + cw, yy), dxfattribs={"layer": "CADRE"})
    m.add_line((x0 + 120, y0), (x0 + 120, y0 + 20), dxfattribs={"layer": "CADRE"})
    _t(m, info.get("projet", "Mur de soutènement"), x0 + 3, y0 + 32.5, 3.0)
    _t(m, info.get("ouvrage", ""), x0 + 3, y0 + 22.5, 2.6)
    _t(m, title, x0 + 3, y0 + 12.5, 3.2)
    _t(m, f"Échelle(s) : {scale_txt}", x0 + 3, y0 + 3.0, 2.3)
    _t(m, f"Planche {sheet}/{n_sheets}", x0 + 123, y0 + 13.0, 2.6)
    _t(m, f"Indice A — {info.get('date', date.today().strftime('%d/%m/%Y'))}", x0 + 123, y0 + 3.0, 2.2)
    _t(m, "Établi avec BatiCalc — à vérifier et viser par l'ingénieur structure", MARGIN + 2, MARGIN / 2 + 1.5, 1.8)
    return (x0, y0, cw, ch)


# ------------------------------------------------------------------ coupe (coffrage ou ferraillage)
def _outline(res: WallResult) -> list[tuple[float, float]]:
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd, kw = g.get("key_depth", 0.0), g.get("key_width", 0.0)
    B = toe + tb + heel
    xk = toe + tb
    bottom = [(xk - kw, 0), (xk - kw, -kd), (xk, -kd), (xk, 0)] if kd > 0 else []
    return [(0, 0), *bottom, (B, 0), (B, hb), (toe + tb, hb), (toe + tb, hb + H), (toe + tb - tt, hb + H),
            (toe, hb), (0, hb)]


def _section(m, v: View, res: WallResult, mode: str, sched: dict | None = None):
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd, kw = g.get("key_depth", 0.0), g.get("key_width", 0.0)
    B = toe + tb + heel
    fiche = w.get("fiche", 0.0) or 0.0
    out = _outline(res)
    P = [v.p(*q) for q in out]
    if mode == "coffrage":
        _hatch_solid(m, P, color=254)
    _pl(m, P, "BETON", close=True, width=0.5)
    # béton de propreté (hors bêche)
    xk0 = toe + tb - kw
    prop = [[(-0.05, -0.05), (xk0 if kd > 0 else B + 0.05, -0.05), (xk0 if kd > 0 else B + 0.05, 0), (-0.05, 0)]]
    if kd > 0:
        prop.append([(toe + tb, -0.05), (B + 0.05, -0.05), (B + 0.05, 0), (toe + tb, 0)])
    for pp in prop:
        _pl(m, [v.p(*q) for q in pp], "BETON", close=True)
    # terrain : terre-plein derrière, terrain aval devant
    ext = 0.6
    xs = toe + tb
    drain_w = 0.40
    back = [(xs, hb + H), (B + ext, hb + H), (B + ext, -0.40 - kd), (B, -0.40 - kd), (B, 0), (B, hb), (xs + drain_w, hb),
            (xs + drain_w, hb + H)]
    if mode == "coffrage":
        _hatch_earth(m, [v.p(*q) for q in back[1:-1] + [(xs + drain_w, hb + H)]], scale=1.0)
    m.add_line(v.p(xs, hb + H), v.p(B + ext, hb + H), dxfattribs={"layer": "TERRE"})
    yg = hb + fiche
    m.add_line(v.p(-ext, yg), v.p(0, yg), dxfattribs={"layer": "TERRE"})
    if mode == "coffrage":
        _hatch_earth(m, [v.p(-ext, yg), v.p(0, yg), v.p(0, -0.40 - kd), v.p(-ext, -0.40 - kd)], scale=1.0)
    # remblai drainant + géotextile + drain + enduit
    dr = [v.p(xs, hb), v.p(xs + drain_w, hb), v.p(xs + drain_w, hb + H - 0.30), v.p(xs, hb + H - 0.30)]
    if mode == "coffrage":
        h = m.add_hatch(color=5, dxfattribs={"layer": "DRAINAGE", "lineweight": 0})
        h.set_pattern_fill("GRAVEL", scale=0.6)
        h.paths.add_polyline_path(dr, is_closed=True)
    m.add_line(v.p(xs + drain_w, hb), v.p(xs + drain_w, hb + H - 0.30), dxfattribs={"layer": "DRAINAGE", "linetype": "DASHED"})
    m.add_circle(v.p(xs + 0.15, hb + 0.08), v.k(0.05), dxfattribs={"layer": "DRAINAGE"})
    _pl(m, [v.p(xs + 0.012, hb), v.p(xs + 0.012, hb + H)], "DRAINAGE", width=0.6)
    if mode == "coffrage":
        # barbacane
        yb = yg + 0.15
        m.add_line(v.p(toe + (tb - tt) * (yb - hb) / H, yb), v.p(xs, yb + 0.03), dxfattribs={"layer": "DRAINAGE"})
        m.add_line(v.p(toe + (tb - tt) * (yb + 0.10 - hb) / H, yb + 0.10), v.p(xs, yb + 0.13), dxfattribs={"layer": "DRAINAGE"})
        _cotes_coffrage(m, v, res)
        xr = B + ext + 0.12
        labels = [
            ((xs + 0.012, hb + 0.85 * H), (xr, hb + 0.92 * H), "Enduit bitumineux 2 couches"),
            ((xs + 0.20, hb + 0.55 * H), (xr, hb + 0.72 * H), "Remblai drainant 0/31,5 (40 cm)"),
            ((xs + drain_w, hb + 0.35 * H), (xr, hb + 0.52 * H), "Géotextile"),
            ((xs + 0.15, hb + 0.08), (xr, hb + 0.30 * H), "Drain PVC Ø100 perforé"),
            ((B + ext / 2, hb + 0.6 * H), (xr, hb + 0.12 * H), "Remblai compacté"),
            ((toe + 0.05, yg + 0.20), (-0.75, yg + 0.90), "Barbacane PVC Ø100 / 2 m"),
            ((0.3, -0.025), (-0.75, -kd - 0.45), "Béton de propreté 5 cm"),
        ]
        if kd > 0:
            labels.append(((xk0 + 0.02, -kd * 0.6), (-0.75, -kd * 0.55 - 0.02), "Bêche à pleine fouille"))
        for (ax, ay), (tx, ty), txt in labels:
            m.add_line(v.p(ax, ay), v.p(tx, ty), dxfattribs={"layer": "TEXTES"})
            _t(m, txt, *v.p(tx, ty), 2.0, al=AL.BOTTOM_LEFT if tx > 0 else AL.BOTTOM_RIGHT)
    else:
        _bars(m, v, res, sched)


def _cotes_coffrage(m, v: View, res: WallResult):
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd, kw = g.get("key_depth", 0.0), g.get("key_width", 0.0)
    B = toe + tb + heel
    yb = -0.05 - kd - 0.25
    _dim(m, v, (0, 0), (toe, 0), (0, yb))
    _dim(m, v, (toe, 0), (toe + tb, 0), (0, yb))
    _dim(m, v, (toe + tb, 0), (B, 0), (0, yb))
    _dim(m, v, (0, 0), (B, 0), (0, yb - 0.22))
    _dim(m, v, (toe + tb - tt, hb + H), (toe + tb, hb + H), (0, hb + H + 0.18))
    _dim(m, v, (0.25, 0), (0.25, hb), (0.25, 0), vertical=True)
    _dim(m, v, (toe, hb), (toe + tb - tt, hb + H), (toe - 0.22, 0), vertical=True)
    _dim(m, v, (0, 0), (toe + tb - tt, hb + H), (-0.45, 0), vertical=True)
    if kd > 0:
        _dim(m, v, (toe + tb - kw, -kd), (toe + tb, -kd), (0, -kd - 0.12))
        _dim(m, v, (toe + tb - kw, 0), (toe + tb - kw, -kd), (toe + tb - kw - 0.20, 0), vertical=True)
    # niveaux
    for y, txt in ((hb + H, "Niveau terre-plein"), (hb + (w.get("fiche") or 0.0), "Terrain aval"),
                   (-0.05, "Fond de fouille"), (-kd if kd else None, "Fond de bêche")):
        if y is None:
            continue
        px, py = v.p(-0.72, y)
        m.add_line((px - 4, py), v.p(-0.6 if y < hb + H - 0.01 else toe + tb - tt, y), dxfattribs={"layer": "COTES"})
        _pl(m, [(px, py), (px + 2.0, py + 2.0), (px - 2.0, py + 2.0)], "COTES", close=True)
        rel = y - (hb + (w.get("fiche") or 0.0))
        _t(m, f"{txt}  {rel:+.2f}".replace(".", ","), px - 3.0, py + 0.6, 2.0, al=AL.BOTTOM_RIGHT)


def _bars(m, v: View, res: WallResult, sched: dict):
    lay = bar_layout(res)
    rows = {r["rep"]: r for r in sched["rows"]}
    for s in lay["shapes"]:
        _pl(m, [v.p(*q) for q in s["path"]], "ACIERS", width=max(0.35, v.k(s["d"] / 1000)))
    for ln in lay["lines"]:
        for q in ln["pts"]:
            c = v.p(*q)
            r = max(0.6, v.k(ln["d"] / 2000))
            h = m.add_hatch(color=1, dxfattribs={"layer": "ACIERS"})
            h.paths.add_edge_path().add_arc(c, r, 0, 360)
    # repères
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd = g.get("key_depth", 0.0)
    B = toe + tb + heel
    c = w["cover"]
    xb = toe + tb - c
    xR, xL = B + 0.75, -0.75
    tags = {1: ((xb, hb + 0.62 * H), (xR, hb + 0.70 * H)),
            3: ((xb - 0.02, hb + 0.10 + 0.25 * 5), (xR, hb + 0.45 * H)),
            2: ((toe + (tb - tt) * 0.5 + c, hb + 0.5 * H), (xL, hb + 0.62 * H)),
            4: ((toe + (tb - tt) * 0.35 + c + 0.01, hb + 0.10 + 0.20 * 5), (xL, hb + 0.40 * H)),
            9: ((toe + tb - tt / 2, hb + H - c), (xR, hb + H + 0.10)),
            5: ((B - 0.40, hb - c), (xR, hb + 0.35)),
            7: ((B - 0.70, hb - c - 0.012), (xR, hb + 0.05)),
            6: ((0.35, c), (xL, -0.30)),
            8: ((0.65, c + 0.012), (xL, 0.10))}
    if kd > 0:
        tags[10] = ((toe + tb - c - 0.015, -kd + 0.12), (xR, -kd - 0.05))
        tags[11] = ((toe + tb - g["key_width"] + c + 0.03, -kd + c + 0.03), (xL, -kd - 0.15))
    for rep, ((ax, ay), (tx, ty)) in tags.items():
        if rep not in rows:
            continue
        r = rows[rep]
        a, t = v.p(ax, ay), v.p(tx, ty)
        m.add_line(a, t, dxfattribs={"layer": "TEXTES"})
        m.add_circle(t, 2.6, dxfattribs={"layer": "TEXTES"})
        _t(m, str(rep), t[0], t[1], 2.4, al=AL.MIDDLE_CENTER)
        lbl = f"HA{r['d']}" + (f" e={r['e'] * 100:g}".replace(".", ",") if r["e"] else "")
        left = tx < 0
        _t(m, lbl, t[0] + (-3.6 if left else 3.6), t[1] - 1.0, 2.1, al=AL.BOTTOM_RIGHT if left else AL.BOTTOM_LEFT)


# ------------------------------------------------------------------ planches
def _section_scale(res: WallResult, max_w: float) -> float:
    """Échelle de la coupe : la plus grande (1/20, 1/25, 1/30…) qui tient sur la feuille."""
    g, w = res.geometry, res.wall
    hgt = g["h_base"] + w["height"] + g.get("key_depth", 0.0) + 1.35
    wid = g["B"] + 1.5
    for sc in (20, 25, 30, 40, 50, 75, 100):
        if hgt * 1000 / sc <= 215 and wid * 1000 / sc <= max_w:
            return float(sc)
    return 100.0


def _sheet_plan(res: WallResult, walls, info, n_sheets) -> ezdxf.document.Drawing:
    doc = _doc()
    m = doc.modelspace()
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd = g.get("key_depth", 0.0)
    B = toe + tb + heel
    fiche = w.get("fiche") or 0.0
    maxL = max(L for _, L in walls)
    hE0 = hb + H + kd
    for sc in (100.0, 125.0, 150.0, 200.0, 250.0, 300.0, 500.0):
        k = 1000 / sc
        need = sum((B + 0.6) * k + 8 + (hE0 + 0.9) * k + 18 + 12 for _ in walls)
        if need <= 232 and maxL * k <= 330:
            break
    _frame(m, "VUE EN PLAN ET ÉLÉVATIONS", f"1/{sc:g}", 1, n_sheets, info)
    y = A3[1] - MARGIN - 12
    for name, L in walls:
        segs = segments(L)
        # --- vue en plan (y vers le haut = côté terres)
        y -= (B + 0.6) * 1000 / sc + 8
        vp = View(MARGIN + 30, y, sc)
        _t(m, f"{name.upper()} — VUE EN PLAN (L = {L:g} m)".replace(".", ","), MARGIN + 30, y + (B + 0.9) * 1000 / sc, 3.0)
        _pl(m, [vp.p(0, 0), vp.p(L, 0), vp.p(L, B), vp.p(0, B)], "CACHE", close=True)            # semelle
        _pl(m, [vp.p(0, toe), vp.p(L, toe), vp.p(L, toe + tb), vp.p(0, toe + tb)], "BETON", close=True, width=0.4)
        _hatch_solid(m, [vp.p(0, toe), vp.p(L, toe), vp.p(L, toe + tb), vp.p(0, toe + tb)], color=254)
        m.add_line(vp.p(0, toe + tb + 0.15), vp.p(L, toe + tb + 0.15), dxfattribs={"layer": "DRAINAGE", "linetype": "DASHED"})
        _t(m, "Côté terres", *vp.p(-0.4, B - 0.2), 2.0, al=AL.TOP_RIGHT)
        _t(m, "Côté aval", *vp.p(-0.4, 0.2), 2.0, al=AL.BOTTOM_RIGHT)
        x = 0.0
        for k, Ls in enumerate(segs):
            if k:
                m.add_line(vp.p(x, -0.1), vp.p(x, B + 0.1), dxfattribs={"layer": "COTES"})
                _t(m, "JD", *vp.p(x, B + 0.12), 1.8, al=AL.BOTTOM_CENTER)
            _dim(m, vp, (x, 0), (x + Ls, 0), (0, -0.75), txt_h=2.0)
            x += Ls
        if len(segs) > 1:
            _dim(m, vp, (0, 0), (L, 0), (0, -1.35), txt_h=2.0)
        # coupe A-A
        xa = 1.0
        for yy, al in ((-0.35, AL.TOP_CENTER), (B + 0.35, AL.BOTTOM_CENTER)):
            m.add_line(vp.p(xa, yy), vp.p(xa, B / 2 + (0.3 if yy > 0 else -0.3)), dxfattribs={"layer": "AXES"})
        _t(m, "A", *vp.p(xa + 0.3, B + 0.35), 2.6)
        _t(m, "A", *vp.p(xa + 0.3, -0.55), 2.6)
        _dim(m, vp, (L, 0), (L, B), (L + 0.6, 0), vertical=True, txt_h=2.0)
        # --- élévation côté aval
        hE = hb + H + kd
        y -= (hE + 0.9) * 1000 / sc + 18
        ve = View(MARGIN + 30, y + kd * 1000 / sc, sc)
        _t(m, f"{name.upper()} — ÉLÉVATION CÔTÉ AVAL", MARGIN + 30, y + (hE + 0.55) * 1000 / sc, 3.0)
        _pl(m, [ve.p(0, hb), ve.p(L, hb), ve.p(L, hb + H), ve.p(0, hb + H)], "BETON", close=True, width=0.4)
        _pl(m, [ve.p(0, 0), ve.p(L, 0), ve.p(L, hb), ve.p(0, hb)], "CACHE", close=True)
        if kd > 0:
            m.add_line(ve.p(0, -kd), ve.p(L, -kd), dxfattribs={"layer": "CACHE"})
        m.add_line(ve.p(-0.5, hb + fiche), ve.p(L + 0.5, hb + fiche), dxfattribs={"layer": "TERRE"})
        x = 0.0
        nb = 0
        for k, Ls in enumerate(segs):
            if k:
                m.add_line(ve.p(x, -kd), ve.p(x, hb + H), dxfattribs={"layer": "COTES"})
            xb = x + 1.0
            while xb < x + Ls - 0.3:
                m.add_circle(ve.p(xb, hb + fiche + 0.20), max(0.8, ve.k(0.05)), dxfattribs={"layer": "DRAINAGE"})
                nb += 1
                xb += 2.0
            x += Ls
        _dim(m, ve, (L, hb), (L, hb + H), (L + 0.6, 0), vertical=True, txt_h=2.0)
        _dim(m, ve, (L, -kd), (L, hb), (L + 0.6, 0), vertical=True, txt_h=2.0)
        _t(m, f"{nb} barbacanes PVC Ø100 (1 tous les 2 m), JD = joint de dilatation 2 cm (polystyrène + "
              f"mastic), {len(segs)} plots de {segs[0]:.2f} m".replace(".", ","), MARGIN + 30, y - 6, 2.0)
        y -= 12
    _t(m, "Implantation des murs à caler sur le plan de masse ; vues en plan dessinées côté aval en bas.",
       A3[0] - MARGIN - 5, A3[1] - MARGIN - 6, 2.0, al=AL.TOP_RIGHT)
    return doc


def _sheet_coffrage(res: WallResult, walls, info, n_sheets) -> ezdxf.document.Drawing:
    doc = _doc()
    m = doc.modelspace()
    g, w = res.geometry, res.wall
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    kd = g.get("key_depth", 0.0)
    sc = _section_scale(res, 150)
    k = 1000 / sc
    _frame(m, "COUPE TYPE A-A — COFFRAGE ET DÉTAILS", f"1/{sc:g} ; détails 1/10", 2, n_sheets, info)
    v = View(MARGIN + 25 + 1.2 * k, MARGIN + 40 + (kd + 0.65) * k, sc)
    _t(m, f"COUPE TYPE A-A — COFFRAGE (1/{sc:g})", MARGIN + 20, A3[1] - MARGIN - 10, 3.5)
    _section(m, v, res, "coffrage")
    # détail : joint de dilatation (vue en plan du voile, 1/10)
    x0, y0 = 335.0, 232.0
    vd = View(x0, y0, 10)
    _t(m, "DÉTAIL JOINT DE DILATATION (plan, 1/10)", x0 - 50, y0 + tb * 100 + 12, 2.6)
    for sgn in (-1, 1):
        pts = [vd.p(0.01 * sgn, 0), vd.p(0.45 * sgn, 0), vd.p(0.45 * sgn, tb), vd.p(0.01 * sgn, tb)]
        _hatch_solid(m, pts, color=254)
        _pl(m, pts, "BETON", close=True, width=0.4)
    _pl(m, [vd.p(-0.01, 0), vd.p(0.01, 0), vd.p(0.01, tb), vd.p(-0.01, tb)], "DRAINAGE", close=True)
    _pl(m, [vd.p(-0.075, tb * 0.5), vd.p(0.075, tb * 0.5)], "DRAINAGE", width=0.8)
    _pl(m, [vd.p(-0.01, -0.005), vd.p(0.01, -0.005)], "DRAINAGE", width=1.2)
    for k, (px, py) in enumerate(((0.0, tb * 0.82), (0.11, tb * 0.5), (0.0, -0.04)), start=1):
        cx, cy = vd.p(px, py)
        cx += 4 if k != 2 else 2.5
        m.add_circle((cx, cy), 1.8, dxfattribs={"layer": "TEXTES"})
        _t(m, str(k), cx, cy, 1.9, al=AL.MIDDLE_CENTER)
    _t(m, "Côté terres", *vd.p(-0.44, tb + 0.03), 1.9)
    _t(m, "Côté aval", *vd.p(-0.44, -0.07), 1.9)
    for k, txt in enumerate(("1  Polystyrène extrudé 2 cm sur toute la hauteur",
                             "2  Joint waterstop PVC 15 cm au milieu du voile",
                             "3  Mastic élastomère sur la face vue",
                             "Aciers horizontaux et filants de semelle interrompus au joint")):
        _t(m, txt, x0 - 50, y0 - 14 - 4 * k, 2.0)
    # détail barbacane (coupe, 1/10)
    x1, y1 = 315.0, 135.0
    vb = View(x1, y1, 10)
    _t(m, "DÉTAIL BARBACANE (coupe, 1/10)", x1 - 30, y1 + 58, 2.6)
    wall_pts = [vb.p(0, -0.15), vb.p(tb, -0.15), vb.p(tb, 0.45), vb.p(0, 0.45)]
    _hatch_solid(m, wall_pts, color=254)
    _pl(m, wall_pts, "BETON", close=True, width=0.4)
    _pl(m, [vb.p(-0.05, -0.02), vb.p(tb + 0.02, 0.0)], "DRAINAGE", width=0.3)
    _pl(m, [vb.p(-0.05, 0.08), vb.p(tb + 0.02, 0.10)], "DRAINAGE", width=0.3)
    filt = [vb.p(tb, -0.10), vb.p(tb + 0.30, -0.10), vb.p(tb + 0.30, 0.25), vb.p(tb, 0.25)]
    h = m.add_hatch(color=5, dxfattribs={"layer": "DRAINAGE"})
    h.set_pattern_fill("GRAVEL", scale=0.4)
    h.paths.add_polyline_path(filt, is_closed=True)
    m.add_line(vb.p(-0.03, 0.03), vb.p(-0.20, 0.30), dxfattribs={"layer": "TEXTES"})
    _t(m, "Tube PVC Ø100, pente 2 %", *vb.p(-0.20, 0.31), 2.0, al=AL.BOTTOM_RIGHT)
    m.add_line(vb.p(tb + 0.15, 0.20), vb.p(tb + 0.15, 0.34), dxfattribs={"layer": "TEXTES"})
    _t(m, "Filtre gravier 15/25", *vb.p(tb + 0.05, 0.35), 2.0)
    _t(m, "+ géotextile", *vb.p(tb + 0.05, 0.31), 2.0)
    _t(m, "Aval", *vb.p(-0.25, -0.12), 1.9)
    _t(m, "Terres", *vb.p(tb + 0.32, -0.12), 1.9)
    # notes générales
    q = res.quantities
    notes = [
        "NOTES GÉNÉRALES",
        "Béton armé dosé à 350 kg/m³ (fc28 = 25 MPa), béton de propreté 150 kg/m³ sur 5 cm.",
        f"Enrobage {w['cover'] * 100:.0f} cm sur toutes les faces. Aciers HA Fe E400.",
        f"Sol d'assise : contrainte admissible {w['sigma_sol'] * 1000:.0f} kPa (étude géotechnique) ;",
        "  fond de fouille réceptionné avant coulage, purger les poches molles.",
        "Bêche coulée à pleine fouille, sans coffrage, contre le sol en place." if kd else "Semelle sur béton de propreté.",
        "Remblai : matériau graveleux non argileux, compacté par couches de 20 cm,",
        "  sans engin lourd à moins de 1,0 m du voile ; remblayer après 28 jours.",
        "Drainage : remblai drainant 40 cm, géotextile, drain PVC Ø100 perforé",
        "  en pied, barbacanes PVC Ø100 tous les 2 m, enduit bitumineux côté terres.",
        "Joints de dilatation tous les 10 m au plus (voir planche 1).",
        f"Surcharge d'exploitation sur le terre-plein : {w['surcharge']:g} kN/m².",
    ]
    if w.get("strip_q"):
        notes.append(f"Bâtiment voisin : {w['strip_q']:g} kN/m² à {w['strip_dist']:g} m du voile, fondé à "
                     f"{w['strip_depth']:g} m".replace(".", ",") + " (à respecter).")
    yy = 106.0
    for k, n in enumerate(notes):
        _t(m, n, 262, yy - k * 4.3, 2.6 if k == 0 else 2.05)
    return doc


def _sheet_ferraillage(res: WallResult, walls, info, n_sheets, sched) -> ezdxf.document.Drawing:
    doc = _doc()
    m = doc.modelspace()
    g = res.geometry
    kd = g.get("key_depth", 0.0)
    sc = _section_scale(res, 150)
    k = 1000 / sc
    _frame(m, "COUPE TYPE A-A — FERRAILLAGE ET NOMENCLATURE", f"1/{sc:g}", 3, n_sheets, info)
    x0 = max(MARGIN + 27 + 0.75 * k, 190 - (g["B"] + 0.75) * k)
    v = View(x0, MARGIN + 40 + (kd + 0.65) * k, sc)
    _t(m, f"COUPE TYPE A-A — FERRAILLAGE (1/{sc:g})", MARGIN + 20, A3[1] - MARGIN - 10, 3.5)
    _section(m, v, res, "ferraillage", sched)
    _t(m, f"Enrobage {res.wall['cover'] * 100:.0f} cm. Recouvrements 50 Ø. Aciers HA Fe E400.",
       MARGIN + 20, MARGIN + 16, 2.2)
    # nomenclature
    nw = len(walls)
    cols = [("Rep", 8), ("Désignation", 52), ("Ø", 9), ("Esp.", 9), ("Forme", 34), ("L (m)", 18)]
    cols += [(f"Nb {n}", 14) for n, _ in walls] + [("L tot (m)", 16), ("Poids (kg)", 16)]
    tw = sum(c[1] for c in cols)
    x0 = A3[0] - MARGIN / 2 - tw - 3
    ytop = A3[1] - MARGIN - 16
    rh = 9.0
    _t(m, "NOMENCLATURE DES ACIERS", x0, ytop + 3, 3.2)
    rows = sched["rows"]
    nrows = len(rows) + 1

    def hline(yy):
        m.add_line((x0, yy), (x0 + tw, yy), dxfattribs={"layer": "CADRE"})
    hline(ytop)
    for i in range(nrows):
        hline(ytop - 7 - i * rh)
    xx = x0
    for name, cwid in cols:
        m.add_line((xx, ytop), (xx, ytop - 7 - (nrows - 1) * rh), dxfattribs={"layer": "CADRE"})
        _t(m, name, xx + cwid / 2, ytop - 3.5, 1.8, al=AL.MIDDLE_CENTER)
        xx += cwid
    m.add_line((xx, ytop), (xx, ytop - 7 - (nrows - 1) * rh), dxfattribs={"layer": "CADRE"})
    for i, r in enumerate(rows):
        yc = ytop - 7 - i * rh - rh / 2
        Lu = r["L"] if r["L"] is not None else r["seg_len"][0]
        Ltxt = f"{Lu:.2f}".replace(".", ",")
        if r["L"] is None and len(set(r["seg_len"])) > 1:
            Ltxt = " / ".join(f"{s_:.2f}".replace(".", ",") for s_ in r["seg_len"])
        vals = [str(r["rep"]), r["nom"], f"HA{r['d']}", (f"{r['e'] * 100:g}".replace(".", ",") if r["e"] else "—"), "",
                Ltxt] + [str(n) for n in r["nb"]] + [f"{sum(r['L_tot']):.1f}".replace(".", ","),
                                                    f"{sum(r['kg']):.1f}".replace(".", ",")]
        xx = x0
        for (name, cwid), val in zip(cols, vals):
            if name == "Désignation":
                _t(m, val, xx + 1.2, yc, 1.75, al=AL.MIDDLE_LEFT)
            elif name == "Forme":
                _shape_sketch(m, r, xx + 2, yc - rh / 2 + 1.5, cwid - 4, rh - 3)
            else:
                _t(m, val, xx + cwid / 2, yc, 1.75 if name.startswith("L (") and "/" in val else 2.0, al=AL.MIDDLE_CENTER)
            xx += cwid
    yb = ytop - 7 - len(rows) * rh - 6
    pdia = "   ".join(f"HA{d} : {kg:,.0f} kg".replace(",", " ") for d, kg in sched["par_diametre_kg"].items())
    _t(m, f"Poids par diamètre — {pdia}", x0, yb, 2.3)
    pm = "   ".join(f"{n} : {kg:,.0f} kg".replace(",", " ") for (n, _), kg in zip(walls, sched["par_mur_kg"]))
    _t(m, f"Poids par mur — {pm}", x0, yb - 5, 2.3)
    _t(m, f"POIDS TOTAL D'ACIER : {sched['total_kg']:,.0f} kg (hors chutes et attaches, + 5 % à commander)"
       .replace(",", " "), x0, yb - 11, 2.8)
    return doc


def _shape_sketch(m, r, x, y, wmax, hmax):
    """Croquis de forme de la barre dans la nomenclature, avec longueurs des branches."""
    if not r["path"]:
        m.add_line((x, y + hmax / 2), (x + wmax, y + hmax / 2), dxfattribs={"layer": "ACIERS"})
        return
    pts = r["path"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    s = min(wmax * 0.7 / max(dx, 1e-6), hmax / max(dy, 1e-6))
    ox = x + (wmax - dx * s) / 2 - 3
    q = [(ox + (p[0] - min(xs)) * s, y + (p[1] - min(ys)) * s) for p in pts]
    _pl(m, q, "ACIERS", width=0.3)
    done = set()
    for a, b, pa, pb in zip(q, q[1:], pts, pts[1:]):
        L = round(math.dist(pa, pb), 2)
        if L in done:
            continue
        done.add(L)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        horiz = abs(b[0] - a[0]) >= abs(b[1] - a[1])
        if horiz:
            low = my <= min(pp[1] for pp in q) + 1e-6 and len(q) > 2
            _t(m, f"{L:.2f}".replace(".", ","), mx + (2.5 if low else 0), my + (-0.6 if low else 0.5), 1.4,
               al=AL.TOP_CENTER if low else AL.BOTTOM_CENTER)
        else:
            _t(m, f"{L:.2f}".replace(".", ","), mx + 0.8, my, 1.4, al=AL.MIDDLE_LEFT)


def _to_pdf(docs, path: Path) -> None:
    import pymupdf
    from ezdxf.addons.drawing import Frontend, RenderContext, layout, pymupdf as pmb
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, LineweightPolicy

    out = pymupdf.open()
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        lineweight_policy=LineweightPolicy.ABSOLUTE, min_lineweight=0.18)
    for doc in docs:
        msp = doc.modelspace()
        be = pmb.PyMuPdfBackend()
        Frontend(RenderContext(doc), be, config=cfg).draw_layout(msp)
        page = layout.Page(A3[0], A3[1], layout.Units.mm, margins=layout.Margins.all(0))
        data = be.get_pdf_bytes(page, settings=layout.Settings(fit_page=False, scale=1.0))
        out.insert_pdf(pymupdf.open("pdf", data))
    out.save(str(path))


def wall_plans(res: WallResult, out_dir, walls: list[tuple[str, float]] | None = None, info: dict | None = None) -> dict:
    """Écrit les 3 planches DXF, le PDF assemblé et renvoie la nomenclature."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    walls = walls or [("Mur", res.wall["length"])]
    info = dict(info or {})
    info.setdefault("ouvrage", "Mur de soutènement en béton armé — H = "
                    f"{res.wall['height']:g} m — ".replace(".", ",") + ", ".join(f"{n} : {L:g} m" for n, L in walls))
    sched = bar_schedule(res, walls)
    docs = [_sheet_plan(res, walls, info, 3), _sheet_coffrage(res, walls, info, 3),
            _sheet_ferraillage(res, walls, info, 3, sched)]
    names = ["01_vue_en_plan_elevations.dxf", "02_coupe_coffrage_details.dxf", "03_ferraillage_nomenclature.dxf"]
    files = []
    for d, n in zip(docs, names):
        d.saveas(out / n)
        files.append(out / n)
    pdf = out / "plans_mur_soutenement.pdf"
    _to_pdf(docs, pdf)
    return {"dxf": [str(f) for f in files], "pdf": str(pdf), "nomenclature": sched}
