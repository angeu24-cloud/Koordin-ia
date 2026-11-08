"""Édition de la structure dans l'application (poteaux, poutres) : conversion du modèle pour
l'éditeur et application des modifications de l'ingénieur."""
from __future__ import annotations

import math

from ..model import Beam, Column
from ..project import Project

NEW = "~"     # préfixe des repères provisoires donnés par l'éditeur aux éléments nouveaux


def _segments(mask_dict) -> list[list[float]]:
    if not mask_dict:
        return []
    from ..slab import SlabMask, outline_segments

    return [[round(v, 2) for v in s] for s in outline_segments(SlabMask.from_dict(mask_dict))]


def to_edit(proj: Project, source: str) -> dict:
    """Modèle → données de l'éditeur (un niveau par plan distinct)."""
    levels = proj.storeys[:1] if proj.single_plan else proj.storeys
    out = {"source": source, "plan_unique": proj.single_plan, "n_niveaux": proj.n, "niveaux": []}
    for k, st in enumerate(levels):
        b = st.plan
        out["niveaux"].append({
            "nom": f"Niveau courant (× {proj.n})" if proj.single_plan else st.name,
            "hauteur": st.height,
            "poteaux": [{"id": c.id, "x": round(c.x, 3), "y": round(c.y, 3), "b": c.b, "h": c.h} for c in b.columns],
            "poutres": [{"id": bm.id, "a": bm.start, "b": bm.end, "l": bm.b, "h": bm.h} for bm in b.beams],
            "murs": [[round(v, 3) for v in w[:4]] + [w[4] if len(w) > 4 else 0.2] for w in (b.walls or [])],
            "contour": _segments(b.footprint or b.slab),
        })
    return out


def apply_edits(proj: Project, data: dict) -> list[str]:
    """Remplace poteaux et poutres de chaque niveau par ceux de l'éditeur. Un poteau nouveau placé au
    droit d'un poteau d'un niveau voisin reprend son repère (continuité verticale)."""
    notes: list[str] = []
    levels = proj.storeys[:1] if proj.single_plan else proj.storeys
    if len(data.get("niveaux", [])) != len(levels):
        raise ValueError("Nombre de niveaux différent du modèle : rechargez l'éditeur.")
    used = {c.id for st in proj.storeys for c in st.plan.columns}
    new_cols: list[list[Column]] = []
    for lv in data["niveaux"]:
        cols = []
        for c in lv["poteaux"]:
            b, h = float(c.get("b") or 0.2), float(c.get("h") or 0.2)
            if not (0.12 <= b <= 1.5 and 0.12 <= h <= 1.5):
                raise ValueError(f"Poteau {c.get('id')} : section {b}×{h} m hors limites (0,12 à 1,50 m).")
            cols.append(Column(str(c["id"]), float(c["x"]), float(c["y"]), b, h))
        new_cols.append(cols)
    # repères : continuité avec les niveaux voisins, sinon numéro libre
    rename: list[dict[str, str]] = [{} for _ in new_cols]
    nxt = [1 + max([int(i[1:]) for i in used if i[1:].isdigit()] or [0])]

    def fresh() -> str:
        while f"P{nxt[0]}" in used:
            nxt[0] += 1
        used.add(f"P{nxt[0]}")
        return f"P{nxt[0]}"

    for k, cols in enumerate(new_cols):
        for c in cols:
            if not c.id.startswith(NEW):
                continue
            match = None
            for kk in (k - 1, k + 1):
                if 0 <= kk < len(new_cols):
                    match = next((o for o in new_cols[kk] if not o.id.startswith(NEW)
                                  and math.hypot(o.x - c.x, o.y - c.y) < 0.15), None)
                    if match:
                        break
            rename[k][c.id] = match.id if match else fresh()
            c.id = rename[k][c.id]
    for k, (st, lv, cols) in enumerate(zip(levels, data["niveaux"], new_cols)):
        ids = [c.id for c in cols]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{st.name} : deux poteaux portent le même repère.")
        cmap = {c.id: c for c in cols}
        beams = []
        for n, bm in enumerate(lv["poutres"], start=1):
            a, b = rename[k].get(bm["a"], bm["a"]), rename[k].get(bm["b"], bm["b"])
            if a not in cmap or b not in cmap or a == b:
                continue
            c1, c2 = cmap[a], cmap[b]
            dx, dy = abs(c2.x - c1.x), abs(c2.y - c1.y)
            if min(dx, dy) > 0.15:
                notes.append(f"{st.name} : poutre {a}–{b} oblique, calculée selon sa grande direction.")
            d = "X" if dx >= dy else "Y"
            if (c1.x, c1.y) > (c2.x, c2.y) if d == "X" else (c1.y, c1.x) > (c2.y, c2.x):
                a, b = b, a          # appuis dans le sens des x (ou y) croissants : files continues
            beams.append(Beam(str(bm.get("id") or f"B{n}"), a, b, float(bm.get("l") or 0.2), float(bm.get("h") or 0.4), d))
        seen = set()
        for bm in beams:     # repères de poutres uniques
            if bm.id in seen or bm.id.startswith(NEW) or bm.id.startswith("N"):
                k_ = 1
                while f"B{k_}" in seen or any(o.id == f"B{k_}" for o in beams):
                    k_ += 1
                bm.id = f"B{k_}"
            seen.add(bm.id)
        st.plan.columns, st.plan.beams, st.plan.panels = cols, beams, []
        st.plan.grid_x = sorted({round(c.x, 2) for c in cols})
        st.plan.grid_y = sorted({round(c.y, 2) for c in cols})
        st.plan.axis_x, st.plan.axis_y = [], []
        st.plan.warnings = [w for w in st.plan.warnings if not w.startswith("Modèle proposé")] + \
            [f"Structure modifiée par l'ingénieur : {len(cols)} poteaux, {len(beams)} poutres."]
    return notes
