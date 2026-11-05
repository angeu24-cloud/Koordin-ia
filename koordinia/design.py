"""Enchaînement du calcul : descente de charges → dimensionnement des éléments."""
from __future__ import annotations

from dataclasses import dataclass, field

from .codes.common import BeamDesign, ColumnDesign, FootingDesign
from typing import TYPE_CHECKING

from .model import Building, LoadSettings
from .takedown import TakedownResult, compute_takedown

if TYPE_CHECKING:
    from .project import Project


@dataclass
class BeamResult:
    beam_id: str
    level: str                # nom du plancher (« Plancher haut RDC », « Terrasse »…)
    span: float
    pu_m: float               # charge ELU équivalente (moment), kN/m
    m0: float                 # moment isostatique ELU, kN.m
    design: BeamDesign
    storey: int = 0           # indice d'étage (0 = bas)
    transfer: list[str] = field(default_factory=list)  # poteaux naissants portés


@dataclass
class ColumnResult:
    column_id: str
    storey: int
    g: float
    q: float
    nser: float
    nu: float
    design: ColumnDesign
    resized: bool = False
    storey_name: str = ""


@dataclass
class FootingResult:
    column_id: str
    design: FootingDesign
    x: float = 0.0
    y: float = 0.0
    on_wall: bool = False      # charge d'un poteau reposant sur un mur (semelle filante à prévoir)


@dataclass
class ProjectResult:
    project: "Project"
    loads: LoadSettings
    code: object
    takedown: TakedownResult
    sigma_sol: float
    beams: list[BeamResult] = field(default_factory=list)
    columns: list[ColumnResult] = field(default_factory=list)
    footings: list[FootingResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def building(self) -> Building:
        """Plan de l'étage le plus haut (compatibilité plan unique)."""
        return self.project.storeys[-1].plan

    @property
    def base_plan(self) -> Building:
        return self.project.storeys[0].plan


def _support_coefs(n_spans: int) -> list[float]:
    """Moments sur appuis en fraction de M0 (méthode forfaitaire simplifiée)."""
    if n_spans == 1:
        return [0.15, 0.15]
    if n_spans == 2:
        return [0.2, 0.6, 0.2]
    inner = [0.5] + [0.4] * (n_spans - 3) + [0.5]
    return [0.2] + inner + [0.2]


def run(model, ls: LoadSettings, code, sigma_sol: float = 0.20, max_column: float = 1.0) -> ProjectResult:
    """Dimensionne un plan unique (Building) ou un projet multi-niveaux (Project)."""
    from .project import Project

    proj = model if isinstance(model, Project) else Project.from_building(model)
    td = compute_takedown(proj, ls)
    res = ProjectResult(proj, ls, code, td, sigma_sol)
    seen_w: list[str] = []
    # remarques des plans : une seule fois par planche, avec les étages concernés
    by_sheet: dict[str, list] = {}
    for st in proj.storeys:
        by_sheet.setdefault(st.sheet.split(" (")[0] or str(id(st.plan)), []).append(st)
    for group in by_sheet.values():
        names = ", ".join(dict.fromkeys(st.name for st in group))
        for w in group[0].plan.warnings:
            tag = w if proj.single_plan else f"{names} — {w}"
            if tag not in seen_w and not w.startswith("Modèle proposé"):
                seen_w.append(tag)
    res.warnings += proj.warnings + seen_w + td.warnings

    # ------------------------------------------------------------------ poutres
    done_plans: set[tuple[int, bool]] = set()
    for sl in td.storeys:
        plan = proj.storeys[sl.index].plan
        if proj.single_plan:
            # plan répété : un seul calcul pour l'étage courant et un pour la terrasse
            key = (id(plan), sl.roof)
            if key in done_plans or (not sl.roof and sl.index != proj.n - 2):
                continue
            done_plans.add(key)
        cols = plan.column_map()
        beams = plan.beam_map()
        label = ("terrasse" if sl.roof else "courant") if proj.single_plan else sl.floor_name
        for line in sl.lines:
            n = len(line.beams)
            sup = _support_coefs(n)
            loads = sl.beam_loads
            m0s = [code.elu(loads[bid].g_m0, loads[bid].q_m0) for bid in line.beams]
            for k, bid in enumerate(line.beams):
                b = beams[bid]
                L = b.length(cols)
                bl = loads[bid]
                m0 = m0s[k]
                end_span = n > 1 and (k == 0 or k == n - 1)
                mt = m0 if n == 1 else (0.85 if end_span else 0.75) * m0
                left = sup[k] * max(m0, m0s[k - 1] if k > 0 else 0)
                right = sup[k + 1] * max(m0, m0s[k + 1] if k + 1 < n else 0)
                ma = max(left, right)
                f_v = 1.15 if n == 2 else (1.10 if n >= 3 else 1.0)
                vu = f_v * code.elu(max(bl.g_rs, bl.g_re), max(bl.q_rs, bl.q_re))
                d = code.beam(b.b, b.h, mt, ma, vu)
                transfer = [p[3] for p in sl.point_loads.get(bid, [])]
                if transfer:
                    d.notes.append(f"Poutre de transfert : porte {', '.join(transfer)}")
                res.beams.append(BeamResult(bid, label, L, 8 * m0 / L ** 2, m0, d, sl.index, transfer))

    # ------------------------------------------------------------------ poteaux
    for cid, stacks in td.columns.items():
        for st in sorted(stacks, key=lambda s: s.storey):
            nser, nu = code.els(st.g, st.q), code.elu(st.g, st.q)
            b, h = st.b, st.h
            lf = 0.7 * st.height
            d = code.column(b, h, nu, lf)
            resized = False
            while not d.ok and max(b, h) < max_column - 1e-9:
                b, h = round(b + 0.05, 2), round(h + 0.05, 2)
                d = code.column(b, h, nu, lf)
                resized = True
            sname = proj.storeys[st.storey - 1].name
            if resized:
                res.warnings.append(
                    f"Poteau {cid} ({sname}) : section portée de {st.b * 100:.0f}×{st.h * 100:.0f} "
                    f"à {b * 100:.0f}×{h * 100:.0f} cm."
                )
            res.columns.append(ColumnResult(cid, st.storey, st.g, st.q, nser, nu, d, resized, sname))

    # --------------------------------------------------------------- fondations
    base = proj.storeys[0].plan
    for c in base.columns:
        r = next(r for r in res.columns if r.column_id == c.id and r.storey == 1)
        fd = code.footing(r.design.b, r.design.h, r.nser, r.nu, sigma_sol)
        res.footings.append(FootingResult(c.id, fd, c.x, c.y))
    for ws in td.wall_supports:
        # le mur descend jusqu'aux fondations : charge ponctuelle sur semelle filante (pré-dimensionnement
        # en semelle isolée équivalente sous un tronçon de mur de 20 cm)
        nser, nu = code.els(ws.g, ws.q), code.elu(ws.g, ws.q)
        fd = code.footing(0.20, 0.20, nser, nu, sigma_sol)
        fd.notes.append("Sous mur : à intégrer à une semelle filante")
        res.footings.append(FootingResult(ws.column_id, fd, ws.x, ws.y, on_wall=True))

    # Recouvrement des semelles → semelles filantes / radier
    fts = [(f.column_id, (f.x, f.y), f.design) for f in res.footings]
    overlaps = []
    for k, (ia, (xa, ya), da) in enumerate(fts):
        for ib, (xb, yb), db in fts[k + 1:]:
            if abs(xa - xb) < (da.A + db.A) / 2 and abs(ya - yb) < (da.B + db.B) / 2:
                overlaps.append(f"{ia}/{ib}")
    if overlaps:
        res.warnings.append(
            f"Semelles qui se chevauchent ({len(overlaps)} paires : {', '.join(overlaps[:8])}"
            f"{'…' if len(overlaps) > 8 else ''}) : prévoir semelles filantes ou jumelées."
        )
    footprint = td.storeys[0].slab_area or td.slab_area
    area_ft = sum(f.design.A * f.design.B for f in res.footings)
    if footprint and area_ft > 0.5 * footprint:
        res.warnings.append(
            f"Surface des semelles = {area_ft / footprint:.0%} de l'emprise : un radier général est à étudier."
        )

    failing = [r for r in res.beams if not r.design.ok] + [r for r in res.columns if not r.design.ok]
    if failing:
        res.warnings.append(f"{len(failing)} élément(s) non vérifié(s) : voir la note de calcul.")
    return res
