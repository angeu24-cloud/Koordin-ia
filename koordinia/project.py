"""Projet multi-niveaux : un modèle par étage, calés dans un même repère.

Convention : l'étage k (du bas vers le haut) est décrit par le plan de son niveau
bas : ses poteaux portent le plancher haut de l'étage k, dont le contour est celui
du plan de l'étage k+1 (ou celui de l'étage k pour la terrasse).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import Drawing
from .levels import (
    StoreyPlan, align_points, assign_sheets, display_name, read_elevations,
)
from .model import Building
from .recognition import build_frame, build_model, cluster, find_columns
from .sheets import Sheet, crop, find_sheets
from .slab import SlabMask


@dataclass
class Storey:
    name: str             # « RDJ », « RDC », « Étage 1 »…
    height: float         # hauteur d'étage (m)
    plan: Building        # poteaux de l'étage + plancher haut (poutres, contour)
    sheet: str = ""       # planche d'origine

    @property
    def floor_name(self) -> str:
        return f"Plancher haut {self.name}"


@dataclass
class Project:
    storeys: list[Storey] = field(default_factory=list)   # du bas vers le haut
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    single_plan: bool = False   # True : un seul plan répété (mode historique)
    name: str = ""              # nom du projet (configuration)

    @property
    def n(self) -> int:
        return len(self.storeys)

    def floor_label(self, k: int) -> str:
        return "Terrasse" if k == self.n - 1 else self.storeys[k].floor_name

    # ------------------------------------------------------------------ fabriques
    @classmethod
    def from_building(cls, bld: Building) -> "Project":
        n = max(1, bld.n_levels)
        names = [f"Niveau {k + 1}" for k in range(n)]
        return cls([Storey(names[k], bld.floor_height, bld) for k in range(n)], bld.source,
                   list(bld.warnings), single_plan=True)

    # ------------------------------------------------------------- sérialisation
    def to_dict(self) -> dict:
        plans: dict[int, int] = {}
        plan_list: list[dict] = []
        storeys = []
        for st in self.storeys:
            key = id(st.plan)
            if key not in plans:
                plans[key] = len(plan_list)
                plan_list.append(st.plan.to_dict())
            storeys.append({"name": st.name, "height": st.height, "sheet": st.sheet, "plan": plans[key]})
        return {"type": "projet", "name": self.name, "source": self.source, "warnings": self.warnings,
                "single_plan": self.single_plan, "plans": plan_list, "storeys": storeys}

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        plans = [Building.from_dict(p) for p in d["plans"]]
        st = [Storey(s["name"], s["height"], plans[s["plan"]], s.get("sheet", "")) for s in d["storeys"]]
        return cls(st, d.get("source", ""), d.get("warnings", []), d.get("single_plan", False), d.get("name", ""))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if d.get("type") == "projet":
            return cls.from_dict(d)
        return cls.from_building(Building.from_dict(d))


def load_model(path: str | Path) -> Project:
    """Charge un modele.json (plan unique) ou un projet.json (multi-niveaux)."""
    return Project.load(path)


# ----------------------------------------------------------------------------- construction
def _column_centers(drawing: Drawing, layer: str | None) -> np.ndarray:
    rects, _ = find_columns(drawing, layer=layer)
    return np.array([[r.cx, r.cy] for r in rects]) if rects else np.zeros((0, 2))


def plan_storeys(drawing: Drawing, *, overrides: dict[str, int] | None = None,
                 heights: dict[str, float] | None = None, default_height: float = 3.0,
                 levels_spec: list[str] | None = None) -> tuple[list[StoreyPlan], list[Sheet], list[str]]:
    """Niveaux + planches affectées (sans construire les modèles)."""
    sheets = find_sheets(drawing)
    notes: list[str] = []
    levels, n1 = read_elevations(drawing, sheets)
    notes += n1
    if levels_spec:
        from .levels import LevelInfo, canonical_level

        names = [canonical_level(n) or n.upper() for n in levels_spec]
        known = {lv.name: lv.elevation for lv in levels}
        elev, out = 0.0, []
        for k, n in enumerate(names):
            if n in known:
                elev = known[n]
            elif k:
                elev += default_height
            out.append(LevelInfo(n, round(elev, 2)))
        levels = out
    if len(levels) < 2:
        raise ValueError("Niveaux introuvables sur les coupes/façades : indiquez-les avec --liste-niveaux "
                         "(ex. « RDC,ETAGE 1,ETAGE 2,TERRASSE ») et --hauteur.")
    storeys, n2 = assign_sheets(levels, sheets, overrides)
    notes += n2
    for sp in storeys:
        if heights and sp.name in heights:
            sp.height = heights[sp.name]
            sp.reason += " ; hauteur imposée"
    return storeys, sheets, notes


def build_project(
    drawing: Drawing,
    *,
    overrides: dict[str, int] | None = None,
    heights: dict[str, float] | None = None,
    levels_spec: list[str] | None = None,
    column_layer: str | None = None,
    max_span: float = 8.0,
    footprint: bool = True,
    default_height: float = 3.0,
    rooms: bool = True,
    usages: list[dict] | None = None,
) -> Project:
    storeys, sheets, notes = plan_storeys(drawing, overrides=overrides, heights=heights,
                                          default_height=default_height, levels_spec=levels_spec)
    proj = Project(source=drawing.source, warnings=list(drawing.warnings) + notes)
    missing = [display_name(sp.name) for sp in storeys if sp.sheet is None]
    if missing:
        raise ValueError(f"Aucune planche pour : {', '.join(missing)}. Utilisez --affectation.")

    sub_of, centers = candidate_resolver(drawing, column_layer)

    proj.warnings += resolve_candidates(storeys, sheets, sub_of, centers)

    # Calage de toutes les planches sur la planche de l'étage le plus haut
    ref_sheet = storeys[-1].sheet
    sub_of(ref_sheet)
    ref_c = centers[ref_sheet.index]
    if len(ref_c) == 0:
        raise ValueError(f"Aucun poteau sur la planche « {ref_sheet.title} ».")
    o_ref = (float(ref_c[:, 0].min()), float(ref_c[:, 1].min()))
    models: dict[int, Building] = {}
    for sp in storeys:
        sh = sp.sheet
        if sh.index in models:
            continue
        sub = sub_of(sh)
        if sh.index == ref_sheet.index:
            t, m = np.zeros(2), len(ref_c)
        else:
            t, m = align_points(ref_c, centers[sh.index])
            ratio = m / max(1, min(len(ref_c), len(centers[sh.index])))
            proj.warnings.append(f"Calage « {sh.title} » sur « {ref_sheet.title} » : {m} poteaux superposés "
                                 f"({ratio:.0%}).")
            if ratio < 0.3:
                proj.warnings.append(f"Calage peu fiable pour « {sh.title} » : vérifier le plan de contrôle.")
        models[sh.index] = build_model(sub, origin=(o_ref[0] + t[0], o_ref[1] + t[1]),
                                       column_layer=column_layer, max_span=max_span, footprint=footprint,
                                       rooms=rooms, usages=usages)

    # Identifiants globaux : poteaux superposés = même repère P…
    pts = [(c.x, c.y) for sp in storeys for c in models[sp.sheet.index].columns]
    gx = cluster([p[0] for p in pts], 0.30)
    gy = cluster([p[1] for p in pts], 0.30)
    keys: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for x, y in pts:
        i = min(range(len(gx)), key=lambda a: abs(gx[a] - x))
        j = min(range(len(gy)), key=lambda a: abs(gy[a] - y))
        keys.setdefault((j, i), []).append((x, y))
    gid = {key: f"P{n}" for n, key in enumerate(sorted(keys), start=1)}

    def global_id(x: float, y: float) -> str:
        i = min(range(len(gx)), key=lambda a: abs(gx[a] - x))
        j = min(range(len(gy)), key=lambda a: abs(gy[a] - y))
        return gid[(j, i)]

    # Un modèle par étage : poteaux de la planche, plancher haut = contour de l'étage supérieur
    for k, sp in enumerate(storeys):
        base = models[sp.sheet.index]
        plan = copy.deepcopy(base)
        for c in plan.columns:
            c.id = global_id(c.x, c.y)
        upper = models[storeys[k + 1].sheet.index] if k + 1 < len(storeys) else base
        plan.footprint = base.slab
        plan.slab = upper.slab
        plan.zones = copy.deepcopy(upper.zones)
        plan.rooms = copy.deepcopy(base.zones)  # locaux du niveau lui-même (finitions, menuiseries)
        # Terrasses / espaces verts de l'étage supérieur situés au-dessus de cet étage : dalle à créer
        if k + 1 < len(storeys) and upper.slab and base.slab:
            added = _add_exterior_zones(plan, base, upper)
            if added > 1.0:
                proj.warnings.append(
                    f"{floor_name(sp)} : {added:.0f} m² de terrasses / espaces verts de "
                    f"{display_name(storeys[k + 1].name)} ajoutés au plancher (au-dessus de {display_name(sp.name)})."
                )
        plan.warnings = [w for w in base.warnings if not w.startswith("Portée")]
        mask = SlabMask.from_dict(plan.slab) if plan.slab else None
        build_frame(plan, mask, max_span=max_span)
        plan.axis_x, plan.axis_y = _labels_for(plan, base)
        if mask is not None and base.slab:
            own = SlabMask.from_dict(base.slab)
            uncovered = own.area - _overlap(own, mask)
            if k + 1 < len(storeys) and uncovered > 0.10 * own.area:
                proj.warnings.append(
                    f"{display_name(sp.name)} : {uncovered:.0f} m² de l'emprise ne sont pas couverts par le plan "
                    f"de {display_name(storeys[k + 1].name)} (cour, rampe, jardin ?) — vérifier s'il existe une dalle."
                )
        proj.storeys.append(Storey(display_name(sp.name), sp.height, plan, sh_title(sp)))
    return proj


def resolve_candidates(storeys: list[StoreyPlan], sheets: list[Sheet], sub_of, centers) -> list[str]:
    """Plusieurs planches pour un même niveau : on garde la mieux superposée à l'étage voisin."""
    from .levels import sheet_levels

    notes: list[str] = []
    for k in range(len(storeys) - 1, -1, -1):
        sp = storeys[k]
        if "plusieurs" not in sp.reason:
            continue
        cands = [s for s in sheets if s.is_plan and sp.name in sheet_levels(s.title)[0]]
        ref = next((storeys[j].sheet for j in range(k + 1, len(storeys))), None) or \
            next((storeys[j].sheet for j in range(k - 1, -1, -1)), None)
        if ref is None:
            continue
        sub_of(ref)
        best, best_score = sp.sheet, -1.0
        for c in cands:
            sub_of(c)
            _, m = align_points(centers[ref.index], centers[c.index])
            score = m / max(1, len(centers[c.index]))  # part des poteaux de la planche qui se superposent
            if score > best_score:
                best, best_score = c, score
        sp.sheet, sp.reason = best, f"la mieux superposée à « {ref.title} »"
        notes.append(f"{display_name(sp.name)} : planche « {best.title} » retenue parmi "
                     f"{len(cands)} candidates ({best_score:.0%} de ses poteaux superposés).")
    return notes


def candidate_resolver(drawing: Drawing, column_layer: str | None = None):
    subs: dict[int, Drawing] = {}
    centers: dict[int, np.ndarray] = {}

    def sub_of(sh: Sheet) -> Drawing:
        if sh.index not in subs:
            subs[sh.index] = crop(drawing, sh.bbox)
            centers[sh.index] = _column_centers(subs[sh.index], column_layer)
        return subs[sh.index]
    return sub_of, centers


def floor_name(sp: StoreyPlan) -> str:
    return f"Plancher haut {display_name(sp.name)}"


def _add_exterior_zones(plan: Building, base: Building, upper: Building) -> float:
    """Ajoute au plancher les zones extérieures (terrasse, jardin) qui surplombent l'étage `base`."""
    up = SlabMask.from_dict(upper.slab)
    own = SlabMask.from_dict(base.slab)
    m = up.mask.copy()
    added = 0
    for z in plan.zones:
        if z["type"] != "exterieur":
            continue
        zm = SlabMask.from_dict(z["cells"])
        if zm.mask.shape != m.shape:
            continue
        cand = zm.mask & ~m
        if not cand.any():
            continue
        jj, ii = np.nonzero(cand)
        x = up.x0 + (ii + 0.5) * up.res
        y = up.y0 + (jj + 0.5) * up.res
        oi = ((x - own.x0) / own.res).astype(int)
        oj = ((y - own.y0) / own.res).astype(int)
        ok = (oi >= 0) & (oi < own.mask.shape[1]) & (oj >= 0) & (oj < own.mask.shape[0])
        over = np.zeros(len(x), dtype=bool)
        over[ok] = own.mask[oj[ok], oi[ok]]
        m[jj[over], ii[over]] = True
        added += int(over.sum())
    if added:
        plan.slab = SlabMask(up.res, up.x0, up.y0, m).to_dict()
    return added * up.res ** 2


def sh_title(sp: StoreyPlan) -> str:
    return f"{sp.sheet.title} ({sp.reason})" if sp.sheet else ""


def _labels_for(plan: Building, base: Building) -> tuple[list[str], list[str]]:
    """Repères d'axes de la planche, ré-associés aux files recalculées."""
    def remap(new: list[float], old: list[float], names: list[str]) -> list[str]:
        if len(names) != len(old):
            return []
        out = []
        for v in new:
            j = min(range(len(old)), key=lambda a: abs(old[a] - v)) if old else None
            out.append(names[j] if j is not None and abs(old[j] - v) < 0.3 else (out[-1] + "+" if out else "0"))
        return out
    return remap(plan.grid_x, base.grid_x, base.axis_x), remap(plan.grid_y, base.grid_y, base.axis_y)


def _overlap(a: SlabMask, b: SlabMask) -> float:
    xa, ya = a.centers()
    ny, nx = b.mask.shape
    i = ((xa - b.x0) / b.res).astype(int)
    j = ((ya - b.y0) / b.res).astype(int)
    ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
    inside = np.zeros(len(xa), dtype=bool)
    inside[ok] = b.mask[j[ok], i[ok]]
    return float(inside.sum()) * a.res ** 2
