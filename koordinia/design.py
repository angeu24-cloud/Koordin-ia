"""Enchaînement du calcul : descente de charges → dimensionnement des éléments."""
from __future__ import annotations

from dataclasses import dataclass, field

from .codes.common import BeamDesign, ColumnDesign, FootingDesign
from .model import Building, LoadSettings
from .takedown import TakedownResult, compute_takedown


@dataclass
class BeamResult:
    beam_id: str
    level: str                # "courant" ou "terrasse"
    span: float
    pu_m: float               # charge ELU équivalente (moment), kN/m
    m0: float                 # moment isostatique ELU, kN.m
    design: BeamDesign


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


@dataclass
class FootingResult:
    column_id: str
    design: FootingDesign


@dataclass
class ProjectResult:
    building: Building
    loads: LoadSettings
    code: object
    takedown: TakedownResult
    sigma_sol: float
    beams: list[BeamResult] = field(default_factory=list)
    columns: list[ColumnResult] = field(default_factory=list)
    footings: list[FootingResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _support_coefs(n_spans: int) -> list[float]:
    """Moments sur appuis en fraction de M0 (méthode forfaitaire simplifiée)."""
    if n_spans == 1:
        return [0.15, 0.15]
    if n_spans == 2:
        return [0.2, 0.6, 0.2]
    inner = [0.5] + [0.4] * (n_spans - 3) + [0.5]
    return [0.2] + inner + [0.2]


def run(bld: Building, ls: LoadSettings, code, sigma_sol: float = 0.20, max_column: float = 1.0) -> ProjectResult:
    td = compute_takedown(bld, ls)
    res = ProjectResult(bld, ls, code, td, sigma_sol)
    res.warnings += bld.warnings + td.warnings
    cols = bld.column_map()
    beams = bld.beam_map()

    # ------------------------------------------------------------------ poutres
    levels = [("courant", td.floor_loads)] if bld.n_levels > 1 else []
    levels.append(("terrasse", td.roof_loads))
    for line in td.lines:
        n = len(line.beams)
        sup = _support_coefs(n)
        for lvl_name, loads in levels:
            m0s = [code.elu(loads[bid].g_m0, loads[bid].q_m0) for bid in line.beams]
            for k, bid in enumerate(line.beams):
                b = beams[bid]
                L = b.length(cols)
                bl = loads[bid]
                m0 = m0s[k]
                end_span = n > 1 and (k == 0 or k == n - 1)
                mt = m0 if n == 1 else (0.85 if end_span else 0.75) * m0
                # moment sur appui : coefficient × max des M0 des travées adjacentes
                left = sup[k] * max(m0, m0s[k - 1] if k > 0 else 0)
                right = sup[k + 1] * max(m0, m0s[k + 1] if k + 1 < n else 0)
                ma = max(left, right)
                f_v = 1.15 if n == 2 else (1.10 if n >= 3 else 1.0)
                vu = f_v * code.elu(max(bl.g_rs, bl.g_re), max(bl.q_rs, bl.q_re))
                d = code.beam(b.b, b.h, mt, ma, vu)
                res.beams.append(BeamResult(bid, lvl_name, L, 8 * m0 / L ** 2, m0, d))

    # ------------------------------------------------------------------ poteaux
    lf = 0.7 * bld.floor_height
    for c in bld.columns:
        for st in sorted(td.columns[c.id], key=lambda s: s.storey):
            nser, nu = code.els(st.g, st.q), code.elu(st.g, st.q)
            b, h = c.b, c.h
            d = code.column(b, h, nu, lf)
            resized = False
            while not d.ok and max(b, h) < max_column - 1e-9:
                b, h = round(b + 0.05, 2), round(h + 0.05, 2)
                d = code.column(b, h, nu, lf)
                resized = True
            if resized:
                res.warnings.append(
                    f"Poteau {c.id} niveau {st.storey} : section portée de {c.b * 100:.0f}×{c.h * 100:.0f} "
                    f"à {b * 100:.0f}×{h * 100:.0f} cm."
                )
            res.columns.append(ColumnResult(c.id, st.storey, st.g, st.q, nser, nu, d, resized))

    # --------------------------------------------------------------- fondations
    for c in bld.columns:
        base = next(r for r in res.columns if r.column_id == c.id and r.storey == 1)
        fd = code.footing(base.design.b, base.design.h, base.nser, base.nu, sigma_sol)
        res.footings.append(FootingResult(c.id, fd))

    # Recouvrement des semelles → semelles filantes / radier
    cols_xy = {c.id: (c.x, c.y) for c in bld.columns}
    fts = [(f.column_id, cols_xy[f.column_id], f.design) for f in res.footings]
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
    area_ft = sum(f.design.A * f.design.B for f in res.footings)
    if td.slab_area and area_ft > 0.5 * td.slab_area:
        res.warnings.append(
            f"Surface des semelles = {area_ft / td.slab_area:.0%} de l'emprise : un radier général est à étudier."
        )

    failing = [r for r in res.beams if not r.design.ok] + [r for r in res.columns if not r.design.ok]
    if failing:
        res.warnings.append(f"{len(failing)} élément(s) non vérifié(s) : voir la note de calcul.")
    return res
