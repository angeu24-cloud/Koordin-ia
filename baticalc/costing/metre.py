"""Métré du gros œuvre à partir des résultats de calcul (quantités par ouvrage + détail)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..codes.common import bar_mass
from ..design import ProjectResult


@dataclass
class DevisSettings:
    categorie: str = "2EME"          # catégorie de terrain des fouilles (1ERE, 2EME, 3EME, 4EME)
    dosage: int = 350                # dosage du béton de fondation (kg/m³)
    hourdis: str = "16 + 4"          # plancher à corps creux du bordereau
    tva: float = 0.18
    ancrage: float = 1.20            # profondeur du fond de fouille si pas de rapport (m)
    debord_fouille: float = 0.30     # sur-largeur de fouille de chaque côté (m)
    propreté: float = 0.05           # épaisseur du béton de propreté (m)
    foisonnement: float = 1.25
    ratio_dalle: float = 80.0        # kg d'acier / m³ (dalles pleines, balcons)
    ratio_escalier: float = 90.0
    ratio_radier: float = 100.0
    epaisseur_plancher: float = 0.20
    second_oeuvre: bool = True       # maçonnerie, enduits, sols, menuiseries, peinture, étanchéité

    @classmethod
    def from_dict(cls, d: dict | None) -> "DevisSettings":
        s = cls()
        for k, v in (d or {}).items():
            k2 = "propreté" if k in ("proprete", "propreté") else k
            if hasattr(s, k2) and v is not None:
                cur = getattr(s, k2)
                setattr(s, k2, bool(v) if isinstance(cur, bool) else type(cur)(v))
        s.categorie = s.categorie.upper().replace("È", "E").replace("ÈRE", "ERE")
        return s


@dataclass
class Quantity:
    code: str
    quantity: float = 0.0
    details: list[tuple[str, float]] = field(default_factory=list)  # (élément / formule, quantité)

    def add(self, label: str, q: float) -> None:
        if q > 0:
            self.quantity += q
            self.details.append((label, q))


def _beam_steel(d, L: float, cover: float) -> float:
    kg = 0.0
    for bars in (d.bars_bottom, d.bars_top):
        if bars:
            kg += bars.n * (L + 2 * 40 * bars.d / 1000) * bar_mass(bars.d)
    if d.stirrups:
        per = 2 * (d.b + d.h - 4 * cover) + 0.20
        kg += (int(L / d.stirrups.s) + 1) * per * bar_mass(d.stirrups.d)
    return kg


def _slab_perimeter(mask_dict) -> float:
    from ..slab import SlabMask, outline_segments

    m = SlabMask.from_dict(mask_dict)
    return float(sum(abs(x1 - x0) + abs(y1 - y0) for x0, y0, x1, y1 in outline_segments(m)))


def compute_metre(res: ProjectResult, s: DevisSettings) -> dict[str, Quantity]:
    from ..outputs.report import quantities as steel_families

    proj, td = res.project, res.takedown
    q: dict[str, Quantity] = {}

    def Q(code: str) -> Quantity:
        return q.setdefault(code, Quantity(code))

    depth = (res.geotech.depth if res.geotech and res.geotech.depth else None) or s.ancrage
    cover = res.code.cover
    e = s.epaisseur_plancher if res.loads.floor_type == "corps_creux" else (
        0.0 if res.loads.floor_type == "charpente" else 0.18)   # chaînages sous charpente : coffrés sur 3 faces

    # --- fondations
    base_cols = {r.column_id: r for r in res.columns if r.storey == 1}
    for ft in res.footings:
        f = ft.design
        a = s.debord_fouille
        fouille = (f.A + 2 * a) * (f.B + 2 * a) * (depth + s.propreté)
        prop = (f.A + 0.2) * (f.B + 0.2) * s.propreté
        semelle = f.A * f.B * f.h
        col = base_cols.get(ft.column_id)
        cb, ch = (col.design.b, col.design.h) if col and not ft.on_wall else (0.0, 0.0)
        amorce_h = max(0.0, depth - f.h)
        amorce = cb * ch * amorce_h
        lbl = f"Semelle {ft.column_id} {f.A:.2f}×{f.B:.2f}×{f.h:.2f}"
        Q("TER-FOU").add(f"{lbl} : ({f.A:.2f}+{2 * a:.2f})×({f.B:.2f}+{2 * a:.2f})×{depth + s.propreté:.2f}", fouille)
        Q("GO-PRO").add(lbl, prop)
        Q("GO-SEM").add(lbl, semelle)
        Q("GO-CSE").add(lbl, 2 * (f.A + f.B) * f.h)
        if amorce:
            Q("GO-AMO").add(f"Amorce {ft.column_id} {cb:.2f}×{ch:.2f}×{amorce_h:.2f}", amorce)
            Q("GO-CAM").add(f"Amorce {ft.column_id}", 2 * (cb + ch) * amorce_h)
        rem = fouille - prop - semelle - amorce
        Q("TER-REM").add(lbl, rem)
        Q("TER-EVA").add(lbl, (fouille - rem) * s.foisonnement)
    if res.raft:
        r = res.raft
        Q("TER-FOR").add(f"Radier {r['aire']:.1f} m² × {r['epaisseur'] + s.propreté:.2f}",
                         r["aire"] * (r["epaisseur"] + s.propreté))
        Q("TER-EVA").add("Radier", r["aire"] * (r["epaisseur"] + s.propreté) * s.foisonnement)
        Q("GO-PRO").add("Radier", r["aire"] * s.propreté)
        Q("GO-RAD").add(f"Radier {r['aire']:.1f} m² × {r['epaisseur']:.2f}", r["aire"] * r["epaisseur"])
        Q("GO-CSE").add("Rives du radier (périmètre estimé 4√A)", 4 * math.sqrt(r["aire"]) * r["epaisseur"])
        Q("GO-HA").add(f"Radier : {s.ratio_radier:g} kg/m³", r["aire"] * r["epaisseur"] * s.ratio_radier)
    for p in res.piles:
        Q("GO-PIE").add(f"Appui {p['poteau']} : Nser {p['nser']:.0f} kN", float(p["n_pieux"] or 1))

    # --- poteaux
    for r in res.columns:
        H = proj.storeys[r.storey - 1].height
        d = r.design
        Q("GO-POT").add(f"{r.column_id} ({r.storey_name}) {d.b:.2f}×{d.h:.2f}×{H:.2f}", d.b * d.h * H)
        Q("GO-CPO").add(f"{r.column_id} ({r.storey_name})", 2 * (d.b + d.h) * H)

    # --- poutres (plan unique : l'étage courant compte pour n − 1 niveaux)
    for r in res.beams:
        n = max(1, proj.n - 1) if (proj.single_plan and r.level == "courant") else 1
        d = r.design
        lbl = f"{r.beam_id} ({r.level}) {d.b:.2f}×{d.h:.2f}×{r.span:.2f}" + (f" × {n} niveaux" if n > 1 else "")
        Q("GO-POU").add(lbl, n * d.b * d.h * r.span)
        Q("GO-CPU").add(lbl, n * (d.b + 2 * max(0.0, d.h - e)) * r.span)
    for r in res.longrines:
        d = r.design
        lbl = f"{r.beam_id} {d.b:.2f}×{d.h:.2f}×{r.span:.2f}"
        Q("GO-LON").add(lbl, d.b * d.h * r.span)
        Q("GO-CLO").add(lbl, 2 * d.h * r.span)
        Q("GO-HA").add(f"Longrine {r.beam_id}", _beam_steel(d, r.span, cover))
    for t in res.transfers:
        d = t.design
        lbl = f"{t.beam_id} ({t.floor}) {d.b:.2f}×{d.h:.2f}×{t.length:.2f}"
        Q("GO-TRF").add(lbl, d.b * d.h * t.length)
        Q("GO-CPU").add(lbl, (d.b + 2 * max(0.0, d.h - e)) * t.length)
        Q("GO-HA").add(f"Transfert {t.beam_id}", _beam_steel(d, t.length, cover))

    # --- planchers
    for k, sl in enumerate(td.storeys):
        plan = proj.storeys[k].plan
        cols = plan.column_map()
        beams_area = sum(b.b * b.length(cols) for b in plan.beams)
        balc = sum(a for z, a, L, g, qq in sl.balconies)
        net = max(0.0, sl.slab_area - beams_area - balc)
        if res.loads.light_roof and sl.roof:
            # toiture légère : charpente bois + couverture (pente ≈ 20° : surface × 1,08)
            per = _slab_perimeter(plan.slab) if plan.slab else 4 * sl.slab_area ** 0.5
            Q("CO-COU").add(f"{sl.floor_name} : {sl.slab_area:.1f} m² × 1,08 (pente)", sl.slab_area * 1.08)
            Q("CO-CHA").add(f"{sl.floor_name} : {sl.slab_area:.1f} m² × 0,025 m³/m²", sl.slab_area * 0.025)
            Q("CO-TRT").add(f"{sl.floor_name} : bois de charpente", sl.slab_area * 0.025)
            Q("CO-RIV").add(f"{sl.floor_name} : périmètre de la toiture", per)
            Q("CO-FAI").add(f"{sl.floor_name} : faîtages ≈ 0,3 × périmètre", 0.3 * per)
            Q("CO-FPL").add(f"{sl.floor_name} : sous-face (pièces couvertes)", net)
        elif res.loads.floor_type == "corps_creux":
            Q("GO-HOU").add(f"{sl.floor_name} : {sl.slab_area:.1f} − poutres {beams_area:.1f} − balcons {balc:.1f}",
                            net)
        else:
            Q("GO-DAL").add(f"{sl.floor_name} : {net:.1f} m² × {e:.2f}", net * e)
            Q("GO-CDA").add(sl.floor_name, net)
            Q("GO-HA").add(f"{sl.floor_name} : {s.ratio_dalle:g} kg/m³", net * e * s.ratio_dalle)
    for b in res.balconies:
        n = max(1, proj.n - 1) if proj.single_plan else 1
        lbl = f"{b.name} ({b.floor}) {b.area:.1f} m² × {b.h:.2f}" + (f" × {n}" if n > 1 else "")
        Q("GO-BAL").add(lbl, n * b.area * b.h)
        Q("GO-CDA").add(lbl, n * b.area)
        Q("GO-HA").add(f"{b.name} ({b.floor}) : {s.ratio_dalle:g} kg/m³", n * b.area * b.h * s.ratio_dalle)
    for st in res.stairs:
        n_f = math.ceil(st.risers / st.flights)
        cosa = math.cos(math.radians(st.angle))
        flight = st.flights * st.width * (st.flight_len / cosa * st.thickness + (n_f - 1) * st.riser_h * st.going / 2)
        landing = st.landing * st.cage[1] * st.thickness
        times = st.floor.count(",") + 1
        vol = (flight + landing) * times
        Q("GO-ESC").add(f"Escalier {st.floor} : volées + palier", vol)
        Q("GO-CDA").add(f"Escalier {st.floor} : sous-faces",
                        times * (st.flights * st.width * st.flight_len / cosa + st.landing * st.cage[1]))
        Q("GO-HA").add(f"Escalier {st.floor} : {s.ratio_escalier:g} kg/m³", vol * s.ratio_escalier)

    # --- aciers des poteaux, poutres et semelles (barres réellement calculées)
    fam = steel_families(res)
    for k_, label in (("poteaux", "Poteaux"), ("poutres", "Poutres"), ("semelles", "Semelles")):
        Q("GO-HA").add(f"{label} (barres calculées)", fam[k_]["acier_kg"])
    return {k: v for k, v in q.items() if v.quantity > 0}
