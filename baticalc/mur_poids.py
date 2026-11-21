"""Murs poids en maçonnerie (moellons, agglos pleins, béton cyclopéen), calcul par mètre linéaire.

Section trapézoïdale : parement arrière vertical (côté terres), fruit sur le parement avant, sur une
semelle en béton non armé (facultative). Poussée de Rankine sur le plan vertical arrière (terre-plein
incliné, surcharge, nappe éventuelle). Vérifications :
- stabilité externe à la base : renversement, glissement, excentricité, contrainte sur le sol ;
- stabilité interne de la maçonnerie à plusieurs niveaux : pas de traction (résultante dans le tiers
  central), compression ≤ résistance admissible, glissement sur les joints (frottement 0,7).
La largeur en pied est augmentée jusqu'à satisfaire toutes les vérifications.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .soutenement import GAMMA_W, Soil, ka_rankine

MATERIALS = {   # poids volumique (kN/m³), compression admissible (MPa), libellé
    "moellons": (22.0, 1.0, "maçonnerie de moellons hourdés au mortier dosé à 350 kg/m³"),
    "agglos": (21.0, 0.8, "maçonnerie d'agglos pleins de béton remplis, mortier dosé à 350 kg/m³"),
    "beton_cyclopeen": (23.0, 2.0, "béton cyclopéen (60 % béton dosé à 250 kg/m³, 40 % moellons)"),
}
GAMMA_CONC = 24.0     # béton non armé de la semelle


@dataclass
class GravityWall:
    height: float                      # hauteur de terres retenues au-dessus de la semelle (m)
    length: float = 1.0
    material: str = "moellons"
    surcharge: float = 10.0
    slope: float = 0.0
    soil: Soil = field(default_factory=Soil)
    sigma_sol: float = 0.15            # MPa (ELS)
    phi_base: float | None = None      # frottement sol / semelle (°), défaut φ du remblai
    fiche: float = 0.0                 # terre devant le mur au-dessus de la semelle (m), butée négligée
    water: float | None = None         # profondeur de la nappe sous le haut du remblai (m), None = drainé
    top_width: float | None = None     # largeur en tête (m), défaut max(0,40 ; H/8)
    base_width: float | None = None    # largeur en pied (m), None = calculée
    footing: bool = True               # semelle en béton
    footing_t: float = 0.40            # épaisseur de la semelle (m)
    footing_ext: float = 0.20          # débord de la semelle de chaque côté (m)
    f_adm: float | None = None         # compression admissible de la maçonnerie (MPa), défaut selon le matériau


@dataclass
class GravityResult:
    wall: dict
    geometry: dict
    ka: float
    forces: dict
    stability: dict
    sections: list
    quantities: dict
    ok: bool
    notes: list = field(default_factory=list)


def _gamma(w: GravityWall) -> float:
    return MATERIALS[w.material][0]


def _pressure(w: GravityWall, z: float) -> tuple[float, float, float, float]:
    """Poussée horizontale et verticale sur une hauteur z depuis le haut, et hauteur de son point
    d'application au-dessus du niveau z (terres + surcharge + eau)."""
    s = w.soil
    beta = math.radians(w.slope)
    ka = ka_rankine(s.phi, w.slope)
    zw = None if w.water is None else max(0.0, min(z, w.water))
    if zw is None or zw >= z:
        Pg, yg = 0.5 * ka * s.gamma * z ** 2, z / 3
        Pw, yw = 0.0, 0.0
    else:
        hw = z - zw
        p1 = ka * s.gamma * zw
        a, b, c = 0.5 * p1 * zw, p1 * hw, 0.5 * ka * (s.gamma_sat - GAMMA_W) * hw ** 2
        Pg = a + b + c
        yg = (a * (hw + zw / 3) + b * hw / 2 + c * hw / 3) / Pg
        Pw, yw = 0.5 * GAMMA_W * hw ** 2, hw / 3
    Pq, yq = ka * w.surcharge * z, z / 2
    PH = (Pg + Pq) * math.cos(beta) + Pw
    PV = (Pg + Pq) * math.sin(beta)
    MH = Pg * math.cos(beta) * yg + Pq * math.cos(beta) * yq + Pw * yw
    return PH, PV, MH, ka


def _geometry(w: GravityWall, B: float) -> dict:
    H = w.height
    b0 = w.top_width if w.top_width is not None else max(0.40, round(H / 8 / 0.05) * 0.05)
    b0 = min(b0, B)
    ext = w.footing_ext if w.footing else 0.0
    t = w.footing_t if w.footing else 0.0
    return {"b0": round(b0, 2), "B": round(B, 2), "fruit": round((B - b0) / H, 3), "semelle_ep": t,
            "semelle_debord": ext, "semelle_largeur": round(B + 2 * ext, 2), "hauteur_totale": round(H + t, 2)}


def _sections(w: GravityWall, g: dict) -> list[dict]:
    """Stabilité interne de la maçonnerie aux niveaux H/4, H/2, 3H/4 et en pied (sur la semelle)."""
    H, gm = w.height, _gamma(w)
    b0, B = g["b0"], g["B"]
    f_adm = (w.f_adm or MATERIALS[w.material][1]) * 1000
    out = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        z = frac * H
        b = b0 + (B - b0) * z / H
        # poids de la maçonnerie au-dessus du niveau z ; bras depuis l'arête avant de la section
        W_rect, x_rect = gm * b0 * z, b - b0 / 2
        W_tri = gm * 0.5 * (b - b0) * z
        x_tri = (b - b0) * 2 / 3
        PH, PV, MH, _ = _pressure(w, z)
        N = W_rect + W_tri + PV
        Ms = W_rect * x_rect + W_tri * x_tri + PV * b
        x = (Ms - MH) / N
        e = b / 2 - x
        if abs(e) <= b / 6:
            smax = N / b * (1 + 6 * abs(e) / b)
        else:
            smax = 2 * N / (3 * max(b / 2 - abs(e), 1e-6))
        slide = 0.7 * N / PH if PH else 99.0
        out.append({"niveau": f"{z:.2f} m sous la tête".replace(".", ","), "z": round(z, 2), "largeur": round(b, 2), "N_kN": round(N, 1),
                    "T_kN": round(PH, 1), "e_m": round(e, 3), "limite_e": round(b / 6, 3), "sigma_max_kPa": round(smax, 1),
                    "f_adm_kPa": round(f_adm, 0), "Fs_joint": round(slide, 2),
                    "ok": abs(e) <= b / 6 and smax <= f_adm and slide >= 1.5})
    return out


def _stability(w: GravityWall, g: dict) -> dict:
    H, s, gm = w.height, w.soil, _gamma(w)
    b0, B, t, ext = g["b0"], g["B"], g["semelle_ep"], g["semelle_debord"]
    Bs = B + 2 * ext
    phi_b = w.phi_base if w.phi_base is not None else s.phi
    Hv = H + t                                     # poussée sur le plan vertical à l'arrière de la semelle
    PH, PV, MH, ka = _pressure(w, Hv)
    # poids (bras depuis l'arête avant de la semelle)
    W_rect, x_rect = gm * b0 * H, ext + B - b0 / 2
    W_tri, x_tri = gm * 0.5 * (B - b0) * H, ext + (B - b0) * 2 / 3
    W_sem, x_sem = GAMMA_CONC * Bs * t, Bs / 2
    W_back, x_back = s.gamma * ext * H, Bs - ext / 2     # terres sur le débord arrière
    W_front, x_front = s.gamma * ext * max(0.0, w.fiche), ext / 2
    W_q, x_q = w.surcharge * ext, Bs - ext / 2
    U = 0.0
    if w.water is not None and w.water < Hv:
        U = 0.5 * GAMMA_W * (Hv - w.water) * Bs
    base_W = W_rect + W_tri + W_sem + W_back + W_front
    base_M = W_rect * x_rect + W_tri * x_tri + W_sem * x_sem + W_back * x_back + W_front * x_front
    V_r = base_W + PV - U                         # renversement / glissement : surcharge sur le débord négligée
    Ms = base_M + PV * Bs
    Mr = MH + U * Bs * 2 / 3
    F_r = Ms / Mr if Mr else 99.0
    F_g = V_r * math.tan(math.radians(phi_b)) / PH if PH else 99.0
    V = V_r + W_q
    x = (Ms + W_q * x_q - Mr) / V
    e = Bs / 2 - x
    if abs(e) <= Bs / 6:
        qmax, qmin = V / Bs * (1 + 6 * e / Bs), V / Bs * (1 - 6 * e / Bs)
        qref = (3 * max(qmax, qmin) + min(qmax, qmin)) / 4
    else:
        qmax, qmin = 2 * V / (3 * max(Bs / 2 - abs(e), 1e-6)), 0.0
        qref = 0.75 * qmax
    adm = w.sigma_sol * 1000
    forces = {"poussee_horizontale_kN_ml": round(PH, 1), "poussee_verticale_kN_ml": round(PV, 1),
              "sous_pression_kN_ml": round(U, 1), "poids_mur_kN_ml": round(W_rect + W_tri, 1),
              "poids_semelle_kN_ml": round(W_sem, 1), "V_kN_ml": round(V, 1),
              "M_stabilisant_kNm_ml": round(Ms, 1), "M_renversant_kNm_ml": round(Mr, 1)}
    st = {"renversement": {"Fs": round(F_r, 2), "min": 1.5, "ok": F_r >= 1.5},
          "glissement": {"Fs": round(F_g, 2), "min": 1.5, "ok": F_g >= 1.5, "phi_base": phi_b},
          "excentricite": {"e": round(e, 3), "limite": round(Bs / 6, 3), "ok": abs(e) <= Bs / 6},
          "sol": {"qmax_kPa": round(max(qmax, qmin), 1), "qmin_kPa": round(min(qmax, qmin), 1), "q_ref_kPa": round(qref, 1),
                  "q_adm_kPa": round(adm, 1), "ok": qref <= adm and max(qmax, qmin) <= 1.33 * adm}}
    return {"stability": st, "forces": forces, "ka": ka}


def _all_ok(st: dict, secs: list) -> bool:
    return all(st[k]["ok"] for k in ("renversement", "glissement", "excentricite", "sol")) and all(s["ok"] for s in secs)


def design_gravity(w: GravityWall) -> GravityResult:
    if w.material not in MATERIALS:
        raise ValueError(f"Matériau inconnu « {w.material} » : {', '.join(MATERIALS)}.")
    if w.slope > w.soil.phi:
        raise ValueError(f"Pente du talus β = {w.slope}° supérieure à φ = {w.soil.phi}° : talus instable.")
    notes: list[str] = []
    H = w.height
    if H > 4.0:
        notes.append("Hauteur > 4 m : un mur poids en maçonnerie devient massif ; comparer avec un mur cantilever en béton armé.")
    if w.base_width is not None:
        B = w.base_width
        g = _geometry(w, B)
        r = _stability(w, g)
        secs = _sections(w, g)
    else:
        B = max(0.40, round(0.35 * H / 0.05) * 0.05)
        for _ in range(200):
            g = _geometry(w, B)
            r = _stability(w, g)
            secs = _sections(w, g)
            if _all_ok(r["stability"], secs):
                break
            B = round(B + 0.05, 2)
    ok = _all_ok(r["stability"], secs)
    if not ok:
        notes.append("Vérifications non satisfaites avec cette géométrie : élargir le mur en pied ou prévoir un mur en béton armé.")
    if g["fruit"] > 0.65:
        notes.append(f"Fruit avant de {g['fruit'] * 100:.0f} % : section très évasée, vérifier l'emprise disponible.")
    notes.append("Mur drainé : barbacanes Ø 100 tous les 2 m, drain en pied et remblai drainant derrière le mur."
                 if w.water is None else "Nappe prise en compte : poussée de l'eau et sous-pression ; un drainage réduirait la section.")
    notes.append(f"Matériau : {MATERIALS[w.material][2]} ; compression admissible {(w.f_adm or MATERIALS[w.material][1]):g} MPa.")
    q = _quantities(w, g)
    return GravityResult(asdict(w), g, round(r["ka"], 3), r["forces"], r["stability"], secs, q, ok, notes)


def _quantities(w: GravityWall, g: dict) -> dict:
    H, L = w.height, w.length
    b0, B, t, Bs = g["b0"], g["B"], g["semelle_ep"], g["semelle_largeur"]
    face = math.hypot(H, B - b0)
    per_ml = {"maconnerie_m3": 0.5 * (b0 + B) * H, "semelle_beton_m3": Bs * t if w.footing else 0.0,
              "beton_proprete_m3": 0.05 * (Bs + 0.2) if w.footing else 0.0,
              "couronnement_m3": b0 * 0.10, "fouille_m3": (Bs + 0.6) * (t + 0.05 + max(0.0, w.fiche) + 0.3),
              "rejointoiement_m2": face, "enduit_bitumineux_m2": H + t, "remblai_drainant_m3": 0.40 * H,
              "drain_ml": 1.0, "geotextile_m2": H + 0.6, "barbacanes_u": 0.5, "coffrage_semelle_m2": 2 * t if w.footing else 0.0}
    total = {k: round(v * L, 2) for k, v in per_ml.items()}
    total["barbacanes_u"] = math.ceil(per_ml["barbacanes_u"] * L)
    return {"par_ml": {k: round(v, 3) for k, v in per_ml.items()}, "total": total, "longueur": L}


# ------------------------------------------------------------------ sorties
def gravity_dxf(res: GravityResult, path) -> None:
    import ezdxf

    g, w = res.geometry, res.wall
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for name, color in (("MACONNERIE", 7), ("SEMELLE", 8), ("TERRE", 8), ("COTES", 3), ("TEXTES", 7), ("DRAINAGE", 5)):
        doc.layers.add(name, color=color)
    m = doc.modelspace()
    H, b0, B, t, ext, Bs = w["height"], g["b0"], g["B"], g["semelle_ep"], g["semelle_debord"], g["semelle_largeur"]
    if t:
        m.add_lwpolyline([(0, 0), (Bs, 0), (Bs, t), (0, t)], close=True, dxfattribs={"layer": "SEMELLE"})
    pts = [(ext, t), (ext + B, t), (ext + B, t + H), (ext + B - b0, t + H)]
    m.add_lwpolyline(pts, close=True, dxfattribs={"layer": "MACONNERIE"})
    h = m.add_hatch(color=8, dxfattribs={"layer": "MACONNERIE"})
    h.set_pattern_fill("AR-BRSTD" if w["material"] == "agglos" else "GRAVEL", scale=0.02)
    h.paths.add_polyline_path(pts, is_closed=True)
    m.add_line((ext + B, t + H), (Bs + 1.5, t + H + 1.5 * math.tan(math.radians(w["slope"]))), dxfattribs={"layer": "TERRE"})
    for k in range(int(H // 1.0) or 1):          # barbacanes
        y = t + 0.30 + k * 1.0
        if y < t + H - 0.2:
            x0 = ext + (B - b0) * (y - t) / H
            m.add_line((x0, y), (ext + B, y + 0.05), dxfattribs={"layer": "DRAINAGE"})
    m.add_lwpolyline([(ext + B, t), (ext + B + 0.40, t), (ext + B + 0.40, t + H - 0.3)], dxfattribs={"layer": "DRAINAGE"})
    tx = lambda s_, x, y, hh=0.08: m.add_text(s_, height=hh, dxfattribs={"layer": "TEXTES", "insert": (x, y)})  # noqa: E731
    tx("COUPE TYPE — MUR POIDS EN MAÇONNERIE", 0, t + H + 0.45, 0.13)
    lab = MATERIALS[w["material"]][2]
    for k, line in enumerate([f"Mur : {lab}", f"Fruit avant {g['fruit'] * 100:.0f} % · couronnement en béton 10 cm",
                              (f"Semelle en béton dosé à 250 kg/m³, {t:.2f} m, débords {ext:.2f} m, sur béton de propreté 5 cm"
                               if t else "Sans semelle : mur fondé directement sur le sol"),
                              "Barbacanes Ø 100 tous les 2 m · drain en pied · remblai drainant 40 cm · géotextile"]):
        tx(line, 0, -0.65 - 0.16 * k, 0.07)
    dim = dict(dxfattribs={"layer": "COTES"},
               override={"dimtxt": 0.07, "dimasz": 0.05, "dimdec": 2, "dimlfac": 1.0, "dimexe": 0.05, "dimexo": 0.05, "dimzin": 8})
    m.add_linear_dim(base=(0, -0.35), p1=(0, 0), p2=(Bs, 0), **dim).render()
    m.add_linear_dim(base=(0, t + 0.0 - 0.15 if not t else -0.18), p1=(ext, t), p2=(ext + B, t), **dim).render()
    m.add_linear_dim(base=(0, t + H + 0.20), p1=(ext + B - b0, t + H), p2=(ext + B, t + H), **dim).render()
    m.add_linear_dim(base=(Bs + 0.35, 0), p1=(Bs, t), p2=(Bs, t + H), angle=90, **dim).render()
    if t:
        m.add_linear_dim(base=(-0.3, 0), p1=(0, 0), p2=(0, t), angle=90, **dim).render()
    doc.saveas(path)


def gravity_html(res: GravityResult) -> str:
    g, w, st = res.geometry, res.wall, res.stability
    ok = lambda b: '<b style="color:#1d7f46">vérifié</b>' if b else '<b style="color:#b42318">NON vérifié</b>'  # noqa: E731
    f = lambda v, n=2: f"{v:,.{n}f}".replace(",", " ").replace(".", ",")  # noqa: E731
    data = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in (
        ("Hauteur de terres retenues", f"{f(w['height'])} m"), ("Longueur du mur", f"{f(w['length'])} m"),
        ("Matériau", MATERIALS[w["material"]][2]), ("Surcharge sur le terre-plein", f"{f(w['surcharge'], 1)} kN/m²"),
        ("Pente du terre-plein", f"{f(w['slope'], 0)}°"),
        ("Remblai γ / φ", f"{f(w['soil']['gamma'], 1)} kN/m³ / {f(w['soil']['phi'], 0)}°"),
        ("Contrainte admissible du sol", f"{f(w['sigma_sol'], 3)} MPa"),
        ("Nappe", "non (mur drainé)" if w["water"] is None else f"à {f(w['water'])} m sous le haut du remblai")))
    geo = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in (
        ("Largeur en tête", f"{f(g['b0'])} m"), ("Largeur en pied", f"{f(g['B'])} m"), ("Fruit du parement avant", f"{g['fruit'] * 100:.0f} %"),
        ("Semelle", f"{f(g['semelle_largeur'])} × {f(g['semelle_ep'])} m (débords {f(g['semelle_debord'])} m)" if g["semelle_ep"] else "sans"),
        ("Hauteur totale", f"{f(g['hauteur_totale'])} m")))
    stab = "".join(f"<tr><td>{n}</td><td>{v}</td><td>{ok(c)}</td></tr>" for n, v, c in (
        ("Renversement", f"Fs = {f(st['renversement']['Fs'])} ≥ 1,5", st["renversement"]["ok"]),
        ("Glissement (butée négligée)", f"Fs = {f(st['glissement']['Fs'])} ≥ 1,5", st["glissement"]["ok"]),
        ("Excentricité", f"e = {f(st['excentricite']['e'], 3)} m ≤ {f(st['excentricite']['limite'], 3)} m", st["excentricite"]["ok"]),
        ("Contrainte sur le sol", f"{f(st['sol']['q_ref_kPa'], 1)} ≤ {f(st['sol']['q_adm_kPa'], 1)} kPa (qmax {f(st['sol']['qmax_kPa'], 1)})",
         st["sol"]["ok"])))
    secs = "".join(f"<tr><td>{s['niveau']}</td><td>{f(s['largeur'])}</td><td>{f(s['N_kN'], 1)}</td><td>{f(s['e_m'], 3)} ≤ {f(s['limite_e'], 3)}</td>"
                   f"<td>{f(s['sigma_max_kPa'], 1)} ≤ {f(s['f_adm_kPa'], 0)}</td><td>{f(s['Fs_joint'])}</td><td>{ok(s['ok'])}</td></tr>"
                   for s in res.sections)
    qt = res.quantities["total"]
    met = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in (
        ("Maçonnerie", f"{f(qt['maconnerie_m3'])} m³"), ("Semelle en béton dosé à 250 kg/m³", f"{f(qt['semelle_beton_m3'])} m³"),
        ("Béton de propreté", f"{f(qt['beton_proprete_m3'])} m³"), ("Couronnement en béton", f"{f(qt['couronnement_m3'])} m³"),
        ("Fouilles", f"{f(qt['fouille_m3'], 1)} m³"), ("Rejointoiement du parement vu", f"{f(qt['rejointoiement_m2'], 1)} m²"),
        ("Enduit bitumineux (face arrière)", f"{f(qt['enduit_bitumineux_m2'], 1)} m²"), ("Remblai drainant", f"{f(qt['remblai_drainant_m3'], 1)} m³"),
        ("Drain Ø 100", f"{f(qt['drain_ml'], 1)} ml"), ("Géotextile", f"{f(qt['geotextile_m2'], 1)} m²"), ("Barbacanes", f"{qt['barbacanes_u']} u")))
    notes = "".join(f"<li>{n}</li>" for n in res.notes)
    return f"""<!doctype html><html lang=fr><head><meta charset=utf-8><title>Mur poids</title><style>
body {{ font: 10pt/1.45 "DejaVu Sans", Arial, sans-serif; color:#1c2430; max-width: 900px; margin: 20px auto; }}
h1 {{ color:#1f4e79; font-size:16pt }} h2 {{ color:#1f4e79; font-size:12pt; border-bottom:2px solid #1f4e79; margin-top:18px }}
table {{ border-collapse:collapse; width:100%; margin:6px 0 }} td, th {{ border:1px solid #9aa8b7; padding:4px 6px; vertical-align:top }}
th {{ background:#1f4e79; color:#fff; text-align:left }}</style></head><body>
<h1>NOTE DE CALCUL — MUR POIDS EN MAÇONNERIE</h1>
<p>Calcul par mètre linéaire ; parement arrière vertical, fruit avant. Résultat global : {ok(res.ok)}.</p>
<h2>1. Données</h2><table>{data}</table>
<h2>2. Géométrie retenue</h2><table>{geo}</table>
<h2>3. Poussées (Rankine, Ka = {f(res.ka, 3)})</h2><table>
<tr><td>Poussée horizontale / verticale (plan arrière, hauteur totale)</td><td>{f(res.forces['poussee_horizontale_kN_ml'], 1)} / {f(res.forces['poussee_verticale_kN_ml'], 1)} kN/ml</td></tr>
<tr><td>Poids du mur / de la semelle</td><td>{f(res.forces['poids_mur_kN_ml'], 1)} / {f(res.forces['poids_semelle_kN_ml'], 1)} kN/ml</td></tr>
<tr><td>Moments stabilisant / renversant</td><td>{f(res.forces['M_stabilisant_kNm_ml'], 1)} / {f(res.forces['M_renversant_kNm_ml'], 1)} kN·m/ml</td></tr></table>
<h2>4. Stabilité externe (base de la semelle)</h2><table><tr><th>Vérification</th><th>Valeur</th><th>Résultat</th></tr>{stab}</table>
<h2>5. Stabilité interne de la maçonnerie</h2>
<table><tr><th>Niveau</th><th>Largeur (m)</th><th>N (kN/ml)</th><th>Excentricité (m) ≤ b/6</th><th>σmax (kPa) ≤ adm.</th><th>Fs joint</th><th></th></tr>{secs}</table>
<h2>6. Métré ({f(res.quantities['longueur'], 1)} ml)</h2><table>{met}</table>
<h2>7. Remarques</h2><ul>{notes}</ul></body></html>"""
