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
class BalconyResult:
    """Balcon en console (dalle en porte-à-faux), calcul par mètre linéaire."""
    floor: str
    name: str
    area: float
    length: float          # porte-à-faux (m)
    g: float               # kN/m² (permanent moyen du balcon)
    q: float
    h: float               # épaisseur retenue (m)
    mu: float              # moment ELU d'encastrement (kN.m/m)
    as_top: float          # aciers supérieurs (cm²/m)
    bars_top: str
    bars_dist: str         # aciers de répartition
    notes: list[str] = field(default_factory=list)


def balcony_design(code, floor: str, name: str, area: float, L: float, g: float, q: float,
                   p_gc: float = 1.0, h_gc: float = 1.0, g_fin: float = 1.0) -> BalconyResult:
    """Console encastrée : charges réparties + garde-corps (poids p_gc kN/m en bout,
    effort horizontal h_gc kN/m à 1 m de haut)."""
    import math

    from .codes.common import bar_area

    notes: list[str] = []
    h = max(0.15, math.ceil(L / 10 * 100) / 100)  # élancement console : h ≥ L/10
    g_tot = 25 * h + g_fin                         # dalle pleine + revêtement
    mu = code.elu(g_tot * L ** 2 / 2 + p_gc * L, q * L ** 2 / 2 + h_gc * 1.0)
    as_top, as_c, n = code.flexure(mu, 1.0, h)
    notes += n
    # choix HAd tous les e cm (e ≤ 25 cm, ≥ 10 cm)
    choice = "—"
    for d in (8, 10, 12, 14, 16):
        e = bar_area(d) / as_top if as_top > 0 else 1.0  # m
        e = min(0.25, math.floor(e * 100) / 100)
        if e >= 0.10:
            choice = f"HA{d} e={e * 100:.0f} cm"
            break
    dist = max(as_top / 4, 1.2)
    d_dist = next(d for d in (6, 8, 10) if bar_area(d) / 0.25 >= dist or d == 10)
    e_dist = min(0.25, math.floor(bar_area(d_dist) / dist * 100) / 100)
    if L > 2.0:
        notes.append("Porte-à-faux > 2 m : vérifier la flèche et le contrepoids côté intérieur")
    if L < 0.3:
        notes.append("Balcon porté (peu ou pas de porte-à-faux)")
    return BalconyResult(floor, name, area, L, g_tot, q, h, mu, as_top, choice, f"HA{d_dist} e={e_dist * 100:.0f} cm", notes)


@dataclass
class TransferResult:
    beam_id: str
    floor: str
    storey: int
    length: float
    supports: str
    carried: list[str]
    m0: float
    vu: float
    design: BeamDesign


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
    balconies: list[BalconyResult] = field(default_factory=list)
    transfers: list[TransferResult] = field(default_factory=list)
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
                bw, bh = b.b, b.h
                # Section insuffisante (aciers comprimés, cisaillement, aciers non logeables) : on l'agrandit
                while (not d.ok or d.as_comp > 0) and bh < 1.20 - 1e-9:
                    bh = round(bh + 0.05, 2)
                    if bh >= 0.80 and bw < 0.50:
                        bw = round(bw + 0.05, 2)
                    w_extra = 25 * (bw * bh - b.b * b.h)  # poids propre supplémentaire
                    d = code.beam(bw, bh, mt + code.elu(w_extra, 0) * L ** 2 / 8 * mt / max(m0, 1e-9),
                                  ma, vu + code.elu(w_extra, 0) * L / 2)
                if (bw, bh) != (b.b, b.h):
                    d.notes.append(f"Section portée de {b.b * 100:.0f}×{b.h * 100:.0f} à {bw * 100:.0f}×{bh * 100:.0f} cm")
                    res.warnings.append(f"Poutre {bid} ({label}) : section portée de {b.b * 100:.0f}×{b.h * 100:.0f} "
                                        f"à {bw * 100:.0f}×{bh * 100:.0f} cm.")
                transfer = [p[3] for p in sl.point_loads.get(bid, [])]
                if transfer:
                    d.notes.append(f"Poutre de transfert : porte {', '.join(transfer)}")
                res.beams.append(BeamResult(bid, label, L, 8 * m0 / L ** 2, m0, d, sl.index, transfer))

    # ------------------------------------------------------- poutres de transfert
    for tb in td.transfers:
        m0 = code.elu(tb.g_m0, tb.q_m0)
        vu = code.elu(tb.g_r, tb.q_r)
        bw, bh = tb.b, tb.h
        d = code.beam(bw, bh, m0, 0.15 * m0, vu)
        while (not d.ok or d.as_comp > 0) and bh < 1.50 - 1e-9:
            bh = round(bh + 0.05, 2)
            if bh >= 0.90 and bw < 0.60:
                bw = round(bw + 0.05, 2)
            extra = 25 * (bw * bh - tb.b * tb.h)
            d = code.beam(bw, bh, m0 + code.elu(extra, 0) * tb.length ** 2 / 8, 0.15 * m0,
                          vu + code.elu(extra, 0) * tb.length / 2)
        d.notes.append("Poutre de transfert créée automatiquement : à valider (appuis, nœuds, flèche)")
        if not d.ok:
            res.warnings.append(f"Poutre de transfert {tb.id} : section insuffisante même à "
                                f"{bw * 100:.0f}×{bh * 100:.0f} cm — revoir la structure.")
        sup = " – ".join(f"{a[0]} {a[1]}" for a in tb.supports)
        res.transfers.append(TransferResult(tb.id, tb.floor_name, tb.storey, tb.length, sup,
                                            [l[3] for l in tb.loads], m0, vu, d))

    # ------------------------------------------------------------------ balcons
    seen_b: set[tuple] = set()
    for sl in td.storeys:
        for z, area, L, g, q in sl.balconies:
            key = (id(proj.storeys[sl.index].plan), z.name, round(area, 1))
            if proj.single_plan and key in seen_b:
                continue
            seen_b.add(key)
            floor = "étage courant" if proj.single_plan else sl.floor_name
            res.balconies.append(balcony_design(code, floor, z.name, area, L, g, q,
                                                g_fin=z.g_finitions if z.g_finitions is not None else 1.0))

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
