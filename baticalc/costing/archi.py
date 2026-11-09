"""Métré du second œuvre à partir des plans d'architecte (murs, ouvertures, locaux).

Par niveau : maçonneries (agglos selon l'épaisseur des murs), enduits, revêtements de
sol selon l'usage des locaux, plinthes, faïence des pièces d'eau, plafonds, peintures,
menuiseries (fenêtres, baies, portes) ; étanchéité de la terrasse.
"""
from __future__ import annotations

from ..slab import SlabMask, outline_segments
from .metre import Quantity

HEIGHTS = {"porte": 2.10, "baie": 2.20, "fenetre": 1.20}
CHAPE_USAGES = ("Parking", "Local technique", "Stockage / archives", "Local ordures", "Réservoir / bâche à eau")
WET_USAGES = ("Sanitaires / vestiaires",)


def _perimeter(mask_dict: dict) -> float:
    return sum(abs(c - a) + abs(d - b) for a, b, c, d in outline_segments(SlabMask.from_dict(mask_dict)))


def _wall_classes(plan, grid: SlabMask) -> dict[int, dict[str, float]]:
    """Longueur des murs par épaisseur (20/15/10 cm) : tronçons alignés fusionnés (recouvrements
    comptés une fois) ; un mur est « en façade » si l'un de ses côtés donne sur l'extérieur."""
    ny, nx = grid.mask.shape
    res = grid.res
    indoor = grid.mask.copy()  # balcons et terrasses = extérieur pour les façades
    for z in (plan.rooms if plan.rooms is not None else plan.zones) or []:
        if z["type"] in ("balcon", "exterieur"):
            zm = SlabMask.from_dict(z["cells"])
            if zm.mask.shape == indoor.shape and zm.x0 == grid.x0 and zm.y0 == grid.y0:
                indoor &= ~zm.mask

    def inside(x: float, y: float) -> bool:
        i, j = int((x - grid.x0) / res), int((y - grid.y0) / res)
        return 0 <= i < nx and 0 <= j < ny and bool(indoor[j, i])

    classes = {20: (0.155, 0.45), 15: (0.115, 0.155), 10: (0.05, 0.115)}
    out: dict[int, dict[str, float]] = {}
    for cls, (lo, hi) in classes.items():
        lines: dict[tuple[str, int], list[tuple[float, float, float]]] = {}
        for x0, y0, x1, y1, t in plan.walls:
            if not lo <= t < hi:
                continue
            if abs(y1 - y0) < 1e-6:
                lines.setdefault(("H", round(y0 / 0.08)), []).append((min(x0, x1), max(x0, x1), t))
            elif abs(x1 - x0) < 1e-6:
                lines.setdefault(("V", round(x0 / 0.08)), []).append((min(y0, y1), max(y0, y1), t))
        total = facade = 0.0
        for (orient, key), segs in lines.items():
            c = key * 0.08
            segs.sort()
            merged: list[list[float]] = []
            for a, b, t in segs:
                if merged and a <= merged[-1][1] + 0.02:
                    merged[-1][1] = max(merged[-1][1], b)
                    merged[-1][2] = max(merged[-1][2], t)
                else:
                    merged.append([a, b, t])
            for a, b, t in merged:
                L = b - a
                total += L
                # façade : échantillons le long du mur, de part et d'autre
                d = t / 2 + 0.25
                n = max(2, int(L / 0.5))
                ext = 0
                for k in range(n):
                    u = a + (k + 0.5) * L / n
                    p1, p2 = ((u, c - d), (u, c + d)) if orient == "H" else ((c - d, u), (c + d, u))
                    if inside(*p1) != inside(*p2):
                        ext += 1
                facade += L * ext / n
        out[cls] = {"total": total, "facade": facade}
    return out


def archi_metre(res, s) -> dict[str, Quantity]:
    proj, td = res.project, res.takedown
    q: dict[str, Quantity] = {}

    def Q(code: str) -> Quantity:
        return q.setdefault(code, Quantity(code))

    e = s.epaisseur_plancher
    for k, st in enumerate(proj.storeys):
        plan = st.plan
        times = 1
        if proj.single_plan:
            if k > 0:
                break
            times = proj.n
        name = st.name if not proj.single_plan else f"niveau courant × {times}"
        fp = plan.footprint or plan.slab
        if not fp:
            continue
        grid = SlabMask.from_dict(fp)
        h_net = max(2.0, st.height - e)
        walls = _wall_classes(plan, grid)
        ops = plan.openings or []
        op_area = {"facade": 0.0, "int": 0.0}
        for o in ops:
            facade = o["facade"] or o["type"] == "fenetre"
            op_area["facade" if facade else "int"] += o["largeur"] * HEIGHTS[o["type"]]
        # --- maçonneries (agglos creux), enduits
        enduit_int = enduit_ext = 0.0
        for cls, w in walls.items():
            if w["total"] < 0.5:
                continue
            area = w["total"] * h_net
            fac = w["facade"] * h_net
            if cls == 20:
                area -= op_area["facade"]
                fac = max(0.0, fac - op_area["facade"])
            elif cls == 15:
                area -= op_area["int"]
            area = max(0.0, area)
            Q(f"MA-A{cls}").add(f"{name} : {w['total']:.1f} ml × {h_net:.2f} m − ouvertures", times * area)
            inner = max(0.0, area - fac)
            enduit_int += 2 * inner + fac
            enduit_ext += fac
        Q("EN-INT").add(f"{name} : murs intérieurs (2 faces) + face intérieure des façades", times * enduit_int)
        Q("EN-EXT").add(f"{name} : face extérieure des façades", times * enduit_ext)
        # --- sols, plinthes, faïence (locaux du niveau)
        rooms = plan.rooms if plan.rooms is not None else plan.zones
        floor_area = grid.area
        special = {"chape": 0.0, "antiderapant": 0.0, "none": 0.0}
        faience = 0.0
        for z in rooms or []:
            if z["type"] == "ouverture" or z["type"] == "escalier":
                special["none"] += z["area"]
            elif z["usage"] in CHAPE_USAGES:
                special["chape"] += z["area"]
            elif z["type"] in ("balcon", "exterieur") or z["usage"] in WET_USAGES:
                special["antiderapant"] += z["area"]
            if z["usage"] in WET_USAGES:
                faience += _perimeter(z["cells"]) * 2.10
        carrelage = max(0.0, floor_area - sum(special.values()))
        if k == 0 and not proj.single_plan or (proj.single_plan and k == 0):
            Q("SO-DAL").add(f"{name} : dallage sur terre-plein (niveau bas)", floor_area if k == 0 else 0)
            Q("SO-POL").add(f"{name} : film polyane", floor_area if k == 0 else 0)
        Q("SO-CAR").add(f"{name} : {floor_area:.1f} m² − locaux particuliers", times * carrelage)
        Q("SO-ANT").add(f"{name} : sanitaires, balcons, terrasses", times * special["antiderapant"])
        Q("SO-CHA").add(f"{name} : parkings, locaux techniques, stockages", times * special["chape"])
        int_len = walls[15]["total"] + walls[10]["total"] + (walls[20]["total"] - walls[20]["facade"])
        plinthes = 2 * int_len + walls[20]["facade"] - sum(o["largeur"] for o in ops if o["type"] != "fenetre")
        Q("SO-PLI").add(f"{name} : 2 × murs intérieurs + façades − portes", times * max(0.0, plinthes))
        Q("SO-FAI").add(f"{name} : périmètre des pièces d'eau × 2,10 m", times * faience)
        # --- plafonds (sous-face du plancher haut) et peintures
        ceil = td.storeys[k].slab_area if k < len(td.storeys) else floor_area
        if not (res.loads.light_roof and k == len(proj.storeys) - 1):   # faux plafond sous charpente
            Q("EN-PLA").add(f"{name} : sous-face du plancher haut", times * ceil)
        Q("PE-INT").add(f"{name} : murs enduits + plafonds", times * (enduit_int + ceil))
        Q("PE-EXT").add(f"{name} : façades", times * enduit_ext)
        # --- menuiseries
        for o in ops:
            w = o["largeur"]
            lbl = f"{name} : {o['type']} {w:.2f} m" + (" (façade)" if o["facade"] else "")
            if o["type"] == "fenetre":
                Q("ME-FEN").add(lbl, times * 1.0)
                Q("ME-FPV").add(lbl, times * max(0.0, w - 1.0))
                Q("ME-APP").add(lbl, times * w)
            elif o["type"] == "baie" or (o["type"] == "porte" and o["facade"] and w > 1.5):
                Q("ME-BAI").add(lbl, times * 1.0)
                Q("ME-BPV").add(lbl, times * max(0.0, w - 1.0))
            elif o["facade"]:
                Q("ME-PEX").add(lbl, times * 1.0)
            else:
                Q("ME-PIN").add(lbl + f" × {HEIGHTS['porte']:.2f}", times * w * HEIGHTS["porte"])
    # --- étanchéité de la terrasse
    if td.storeys and not res.loads.light_roof:
        roof = td.storeys[-1]
        plan = proj.storeys[-1].plan
        per = _perimeter(plan.slab) if plan.slab else 0.0
        Q("ET-FPE").add(f"Terrasse : {roof.slab_area:.1f} m²", roof.slab_area)
        Q("ET-ETA").add(f"Terrasse : {roof.slab_area:.1f} m²", roof.slab_area)
        Q("ET-REL").add(f"Terrasse : périmètre {per:.1f} ml", per)
        if res.loads.q_roof >= 1.5:
            Q("ET-PRO").add("Terrasse accessible : protection", roof.slab_area)
    return {k: v for k, v in q.items() if v.quantity > 0}
