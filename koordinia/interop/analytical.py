"""Modèle analytique filaire (nœuds, barres, appuis, cas de charge) commun aux échanges
avec les logiciels de calcul (Robot Structural Analysis, Graitec Advance Design, SAF).

- poteaux : barres verticales sur la hauteur de chaque niveau ;
- poutres et poutres de transfert : barres au niveau du plancher, recoupées à chaque nœud
  rencontré (poutre portant une autre poutre, poteau naissant) pour assurer la continuité ;
- appuis : encastrement en pied des poteaux du niveau bas ; articulation sous tout pied de
  poteau ou extrémité de poutre qui ne repose sur rien (mur porteur, appui manquant) ;
- charges :
  - cas « PP » : poids propre des barres, calculé par le logiciel ;
  - cas « G » et « Q » : charges de plancher réparties par Koordin-IA sur chaque poutre
    (charge uniforme équivalente, kN/m), y compris les zones et balcons, plus les surfaces
    reportées directement sur les poteaux (charges nodales).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..design import ProjectResult
from ..takedown import CONCRETE

TOL = 0.05  # m
SNAP = 0.60  # m : décalage maximal raccordé automatiquement


@dataclass
class Node:
    name: str
    x: float
    y: float
    z: float


@dataclass
class Member:
    name: str
    kind: str          # "Column" | "Beam"
    section: str
    n1: str
    n2: str
    ref: str           # repère Koordin-IA (P12, B3…)
    storey: int


@dataclass
class Section:
    name: str
    kind: str          # "Column" | "Beam"
    b: float           # largeur (m) : selon X pour un poteau, largeur d'âme pour une poutre
    h: float           # hauteur (m) : selon Y pour un poteau, retombée pour une poutre


@dataclass
class AnalyticalModel:
    name: str
    concrete: str
    nodes: dict[str, Node] = field(default_factory=dict)
    members: list[Member] = field(default_factory=list)
    sections: dict[str, Section] = field(default_factory=dict)
    supports: list[tuple[str, str, str]] = field(default_factory=list)   # (nœud, "Fixed"|"Hinged", repère)
    storeys: list[tuple[str, float]] = field(default_factory=list)       # (nom, altitude)
    line_loads: dict[str, list[tuple[str, float]]] = field(default_factory=dict)   # cas → [(barre, kN/m)]
    node_loads: dict[str, list[tuple[str, float]]] = field(default_factory=dict)   # cas → [(nœud, kN)]
    notes: list[str] = field(default_factory=list)

    def member_map(self) -> dict[str, Member]:
        return {m.name: m for m in self.members}


def _concrete_class(res: ProjectResult) -> str:
    fc = getattr(res.code, "fc28", None) or getattr(res.code, "fck", None) or 25
    table = {20: "C20/25", 25: "C25/30", 30: "C30/37", 35: "C35/45", 40: "C40/50"}
    return table.get(int(round(fc)), f"C{int(round(fc))}/{int(round(fc)) + 5}")


def build_analytical(res: ProjectResult) -> AnalyticalModel:
    from ..outputs.viewer import viewer_data

    data = viewer_data(res)
    proj = res.project
    model = AnalyticalModel(proj.name or "Projet Koordin-IA", _concrete_class(res))
    td = res.takedown
    nodes: dict[tuple[int, int, int], str] = {}

    def node(x: float, y: float, z: float) -> str:
        key = (round(x / TOL), round(y / TOL), round(z / 0.01))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k2 = (key[0] + dx, key[1] + dy, key[2])
                if k2 in nodes:
                    n = model.nodes[nodes[k2]]
                    if abs(n.x - x) <= TOL and abs(n.y - y) <= TOL:
                        return nodes[k2]
        name = f"N{len(model.nodes) + 1}"
        model.nodes[name] = Node(name, round(x, 3), round(y, 3), round(z, 3))
        nodes[key] = name
        return name

    def section(kind: str, b: float, h: float) -> str:
        name = f"{'P' if kind == 'Column' else 'B'} {b * 100:.0f}x{h * 100:.0f}"
        model.sections.setdefault(name, Section(name, kind, round(b, 3), round(h, 3)))
        return name

    beam_raw: list[tuple[int, dict, str, str, float]] = []
    for k, lv in enumerate(data["niveaux"]):
        z0, H = lv["altitude"], lv["hauteur"]
        z1 = round(z0 + H, 3)
        model.storeys.append((lv["nom"], z0))
        for c in lv["colonnes"]:
            a, b = node(c["x"], c["y"], z0), node(c["x"], c["y"], z1)
            model.members.append(Member(f"M{len(model.members) + 1}", "Column", section("Column", c["b"], c["h"]),
                                        a, b, c["id"], k))
        for bm in lv["poutres"]:
            if math.hypot(bm["x2"] - bm["x1"], bm["y2"] - bm["y1"]) < TOL:
                continue
            a, b = node(bm["x1"], bm["y1"], z1), node(bm["x2"], bm["y2"], z1)
            beam_raw.append((k, bm, a, b, z1))
    # poutres recoupées aux nœuds intermédiaires (même plancher)
    by_z: dict[float, list[str]] = {}
    for n in model.nodes.values():
        by_z.setdefault(n.z, []).append(n.name)
    beam_parts: dict[tuple[int, str], list[str]] = {}
    for k, bm, a, b, z in beam_raw:
        A, B = model.nodes[a], model.nodes[b]
        L = math.hypot(B.x - A.x, B.y - A.y)
        ux, uy = (B.x - A.x) / L, (B.y - A.y) / L
        inner = []
        for nn in by_z.get(z, []):
            if nn in (a, b):
                continue
            N = model.nodes[nn]
            t = (N.x - A.x) * ux + (N.y - A.y) * uy
            d = abs(-(N.x - A.x) * uy + (N.y - A.y) * ux)
            if TOL < t < L - TOL and d <= TOL:
                inner.append((t, nn))
        chain = [a] + [nn for _, nn in sorted(inner)] + [b]
        sec = section("Beam", bm["b"], bm["h"])
        for n1, n2 in zip(chain, chain[1:]):
            m = Member(f"M{len(model.members) + 1}", "Beam", sec, n1, n2, bm["id"], k)
            model.members.append(m)
            beam_parts.setdefault((k, bm["id"]), []).append(m.name)
    # raccordement des extrémités libres (poteau naissant décalé de l'axe de sa poutre, about de
    # poutre de transfert) : nœud voisin, sinon point de la poutre la plus proche (≤ SNAP)
    z_base = min((n.z for n in model.nodes.values()), default=0.0)
    snapped = _snap_free_ends(model, beam_parts, z_base)
    if snapped:
        model.notes.append(f"{len(snapped)} extrémité(s) raccordée(s) à l'élément porteur le plus proche "
                           f"(décalage ≤ {SNAP:g} m) : " + ", ".join(sorted(set(snapped))) + ".")
    # appuis
    degree: dict[str, int] = {}
    for m in model.members:
        degree[m.n1] = degree.get(m.n1, 0) + 1
        degree[m.n2] = degree.get(m.n2, 0) + 1
    supported = set()
    for m in model.members:
        if m.kind == "Column" and model.nodes[m.n1].z <= z_base + 1e-6 and m.n1 not in supported:
            model.supports.append((m.n1, "Fixed", m.ref))
            supported.add(m.n1)
    hanging = []
    for m in model.members:
        ends = [m.n1] if m.kind == "Column" else [m.n1, m.n2]
        for n in ends:
            if degree[n] == 1 and n not in supported:
                model.supports.append((n, "Hinged", m.ref))
                supported.add(n)
                hanging.append(m.ref)
    if hanging:
        on_wall = {w.column_id for w in td.wall_supports}
        walls = sorted({h for h in hanging if h in on_wall}, key=lambda r: (len(r), r))
        other = sorted({h for h in hanging if h not in on_wall}, key=lambda r: (len(r), r))
        if walls:
            model.notes.append("Appuis articulés (murs porteurs, non modélisés) sous " + ", ".join(walls) + ".")
        if other:
            model.notes.append("Appuis articulés PROVISOIRES sous " + ", ".join(other) + " : aucun élément porteur "
                               "trouvé (poteau ou poutre manquant, portée trop longue) — à corriger dans le modèle.")
    # charges de plancher (G, Q) réparties par Koordin-IA
    model.line_loads = {"G": [], "Q": []}
    model.node_loads = {"G": [], "Q": []}
    for k, lv in enumerate(data["niveaux"]):
        sl = td.storeys[k]
        plan = proj.storeys[k].plan
        cols = plan.column_map()
        for b in plan.beams:
            parts = beam_parts.get((k, b.id))
            bl = sl.beam_loads.get(b.id)
            if not parts or bl is None:
                continue
            L = b.length(cols)
            if L < TOL:
                continue
            g_pts = sum(p[1] for p in sl.point_loads.get(b.id, []))
            q_pts = sum(p[2] for p in sl.point_loads.get(b.id, []))
            g = (bl.g_tot - g_pts - CONCRETE * b.b * b.h * L) / L   # plancher + façade, sans poids propre
            q = (bl.q_tot - q_pts) / L
            for mname in parts:
                if g > 1e-3:
                    model.line_loads["G"].append((mname, round(g, 3)))
                if q > 1e-3:
                    model.line_loads["Q"].append((mname, round(q, 3)))
        top = round(lv["altitude"] + lv["hauteur"], 3)
        for c in plan.columns:
            gd, qd = sl.direct_g.get(c.id, 0.0), sl.direct_q.get(c.id, 0.0)
            if gd > 1e-3 or qd > 1e-3:
                n = node(c.x, c.y, top)
                if gd > 1e-3:
                    model.node_loads["G"].append((n, round(gd, 2)))
                if qd > 1e-3:
                    model.node_loads["Q"].append((n, round(qd, 2)))
    model.notes.append("Charges G et Q de plancher réparties par Koordin-IA sur les poutres (charge uniforme "
                       "équivalente, même résultante). Poids propre des barres calculé par le logiciel (cas PP).")
    return model


def _snap_free_ends(model: AnalyticalModel, beam_parts: dict, z_base: float) -> list[str]:
    def degrees() -> dict[str, int]:
        d: dict[str, int] = {}
        for m in model.members:
            d[m.n1] = d.get(m.n1, 0) + 1
            d[m.n2] = d.get(m.n2, 0) + 1
        return d

    done: list[str] = []
    deg = degrees()
    for m in list(model.members):
        ends = ["n1"] if m.kind == "Column" else ["n1", "n2"]
        for attr in ends:
            n = getattr(m, attr)
            N = model.nodes[n]
            if deg.get(n, 0) != 1 or (m.kind == "Column" and N.z <= z_base + 1e-6):
                continue
            other = getattr(m, "n2" if attr == "n1" else "n1")
            # a) nœud porteur voisin au même niveau
            cands = [(math.hypot(o.x - N.x, o.y - N.y), o.name) for o in model.nodes.values()
                     if o.name not in (n, other) and abs(o.z - N.z) < 1e-6 and deg.get(o.name, 0) >= 1]
            cands = [c for c in cands if c[0] <= SNAP]
            target = min(cands)[1] if cands else None
            # b) sinon point de la poutre la plus proche
            if target is None:
                best = None
                for b in model.members:
                    if b is m or b.kind != "Beam" or n in (b.n1, b.n2):
                        continue
                    A, B = model.nodes[b.n1], model.nodes[b.n2]
                    if abs(A.z - N.z) > 1e-6 or abs(B.z - N.z) > 1e-6:
                        continue
                    L = math.hypot(B.x - A.x, B.y - A.y)
                    ux, uy = (B.x - A.x) / L, (B.y - A.y) / L
                    t = (N.x - A.x) * ux + (N.y - A.y) * uy
                    dist = abs(-(N.x - A.x) * uy + (N.y - A.y) * ux)
                    if TOL < t < L - TOL and dist <= SNAP and (best is None or dist < best[0]):
                        best = (dist, b, A.x + t * ux, A.y + t * uy)
                if best:
                    _, b, x, y = best
                    name = f"N{len(model.nodes) + 1}"
                    model.nodes[name] = Node(name, round(x, 3), round(y, 3), N.z)
                    new = Member(f"M{len(model.members) + 1}", "Beam", b.section, name, b.n2, b.ref, b.storey)
                    b.n2 = name
                    model.members.append(new)
                    for parts in beam_parts.values():
                        if b.name in parts:
                            parts.insert(parts.index(b.name) + 1, new.name)
                    target = name
            if target:
                setattr(m, attr, target)
                done.append(m.ref)
                deg = degrees()
    return done
