"""Murs de soutènement en béton armé (mur cantilever en T renversé), calcul par mètre linéaire.

Poussée des terres de Rankine sur l'écran fictif vertical passant par l'extrémité du talon (talus
incliné de β admis), surcharge uniforme q, nappe éventuelle derrière le mur. Vérifications de
stabilité externe (renversement, glissement, excentricité, contrainte sur le sol de fondation) aux
coefficients usuels (Fascicule 62 titre V, DTU 13.12), puis ferraillage à l'ELU du voile, du talon
et du patin avec le règlement choisi (BAEL 91 ou Eurocode 2) et vérification à l'effort tranchant
sans armatures transversales. Prédimensionnement automatique de la semelle si elle n'est pas imposée.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .codes.common import bar_area, bar_mass

GAMMA_BA = 25.0     # kN/m³
GAMMA_W = 10.0      # kN/m³


@dataclass
class Soil:
    gamma: float = 18.0        # poids volumique du remblai (kN/m³)
    phi: float = 30.0          # angle de frottement interne du remblai (°)
    gamma_sat: float = 20.0    # poids volumique saturé (sous la nappe)


@dataclass
class RetainingWall:
    """Données d'un mur cantilever. Hauteurs en m, charges en kN/m², contrainte en MPa."""
    height: float                     # hauteur du voile au-dessus de la semelle (terres retenues)
    length: float = 1.0               # longueur du mur (métré)
    surcharge: float = 10.0           # q sur le terre-plein (kN/m²)
    slope: float = 0.0                # pente du terre-plein β (°)
    soil: Soil = field(default_factory=Soil)
    sigma_sol: float = 0.15           # contrainte admissible du sol de fondation (MPa, ELS)
    phi_base: float | None = None     # frottement sol / semelle (°) ; défaut : 2/3·φ du remblai, base coulée en place → φ
    fiche: float = 0.0                # hauteur de terre devant le mur au-dessus de la semelle (m) ; butée négligée
    water: float | None = None        # profondeur de la nappe sous le haut du remblai (m), None = mur drainé
    # géométrie (None = prédimensionnée)
    t_top: float = 0.20               # épaisseur du voile en tête
    t_base: float | None = None       # épaisseur du voile en pied
    h_base: float | None = None       # épaisseur de la semelle
    toe: float | None = None          # longueur du patin (devant)
    heel: float | None = None         # longueur du talon (derrière)
    cover: float = 0.05               # enrobage (parement au contact des terres)
    key_depth: float = 0.0            # bêche sous le voile : hauteur sous la semelle (m), 0 = sans bêche
    key_width: float = 0.30           # largeur de la bêche (m)


@dataclass
class WallResult:
    wall: dict
    geometry: dict
    ka: float
    forces: dict
    stability: dict
    reinforcement: dict
    quantities: dict
    ok: bool
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ poussées
def ka_rankine(phi: float, beta: float = 0.0) -> float:
    """Coefficient de poussée de Rankine pour un terre-plein incliné de β (β ≤ φ)."""
    p, b = math.radians(phi), math.radians(min(beta, phi))
    cb, cp = math.cos(b), math.cos(p)
    root = math.sqrt(max(0.0, cb ** 2 - cp ** 2))
    return cb * (cb - root) / (cb + root)


def predimension(w: RetainingWall) -> dict:
    """Règles usuelles : semelle ≈ 0,5 à 0,7 H, patin ≈ B/4, voile e ≥ H/12, semelle e ≥ H/10."""
    H = w.height
    t_base = w.t_base if w.t_base is not None else max(w.t_top, math.ceil(max(0.20, H / 12) / 0.05) * 0.05)
    h_base = w.h_base if w.h_base is not None else max(0.30, math.ceil(H / 10 / 0.05) * 0.05)
    B = max(1.20, 0.55 * (H + h_base))
    toe = w.toe if w.toe is not None else max(0.30, round(B / 4 / 0.05) * 0.05)
    heel = w.heel if w.heel is not None else max(0.30, round((B - toe - t_base) / 0.05) * 0.05)
    return {k: round(v, 2) for k, v in
            {"t_top": w.t_top, "t_base": t_base, "h_base": h_base, "toe": toe, "heel": heel}.items()}


# ------------------------------------------------------------------ stabilité
def _actions(w: RetainingWall, g: dict, with_q_on_heel: bool) -> dict:
    """Forces par ml (kN) et moments par rapport à l'arête avant du patin (kN·m)."""
    H, s = w.height, w.soil
    hb, toe, heel, tt, tb = g["h_base"], g["toe"], g["heel"], g["t_top"], g["t_base"]
    B = toe + tb + heel
    beta = math.radians(w.slope)
    rise = heel * math.tan(beta)
    Hv = H + hb + rise                          # hauteur de l'écran fictif (extrémité du talon)
    ka = ka_rankine(s.phi, w.slope)
    # --- poussées (composante horizontale ; la composante verticale du talus incliné est stabilisante)
    zw = None if w.water is None else max(0.0, min(Hv, w.water))
    if zw is None:
        Pg = 0.5 * ka * s.gamma * Hv ** 2
        yg = Hv / 3
        Pw, yw = 0.0, 0.0
    else:
        hw = Hv - zw
        g1 = s.gamma
        g2 = s.gamma_sat - GAMMA_W
        p1 = ka * g1 * zw                       # pression au niveau de la nappe
        P_a = 0.5 * p1 * zw                     # triangle au-dessus de la nappe
        P_b = p1 * hw                           # rectangle sous la nappe
        P_c = 0.5 * ka * g2 * hw ** 2           # triangle déjaugé
        Pg = P_a + P_b + P_c
        yg = (P_a * (hw + zw / 3) + P_b * hw / 2 + P_c * hw / 3) / Pg if Pg else 0.0
        Pw = 0.5 * GAMMA_W * hw ** 2
        yw = hw / 3
    Pq = ka * w.surcharge * Hv
    yq = Hv / 2
    PgH, PgV = Pg * math.cos(beta), Pg * math.sin(beta)
    PqH, PqV = Pq * math.cos(beta), Pq * math.sin(beta)
    # --- poids (bras de levier depuis l'arête avant du patin)
    W_sem = GAMMA_BA * B * hb
    W_v1 = GAMMA_BA * tt * H
    x_v1 = toe + tb - tt / 2
    W_v2 = GAMMA_BA * 0.5 * (tb - tt) * H
    x_v2 = toe + (tb - tt) * 2 / 3
    W_terre = s.gamma * heel * H + s.gamma * 0.5 * heel * rise
    x_terre = toe + tb + heel / 2
    W_toe = s.gamma * toe * max(0.0, w.fiche)
    W_q = w.surcharge * heel if with_q_on_heel else 0.0
    kd, kw = max(0.0, w.key_depth), w.key_width
    W_key = GAMMA_BA * kw * kd                  # bêche sous le voile, parement arrière aligné sur le voile
    x_key = toe + tb - kw / 2
    U = 0.0
    if zw is not None:                          # sous-pression (diagramme triangulaire, drainage nul côté aval)
        U = 0.5 * GAMMA_W * (Hv - zw) * B
    V = W_sem + W_v1 + W_v2 + W_terre + W_toe + W_q + W_key + PgV + PqV - U
    Ms = (W_sem * B / 2 + W_v1 * x_v1 + W_v2 * x_v2 + W_terre * x_terre + W_toe * toe / 2
          + W_q * x_terre + W_key * x_key + (PgV + PqV) * B)
    Mr = PgH * yg + PqH * yq + Pw * yw + U * B * 2 / 3
    return {"B": B, "Hv": Hv, "ka": ka, "PgH": PgH, "PqH": PqH, "Pw": Pw, "yg": yg, "yq": yq, "yw": yw,
            "W": {"semelle": W_sem, "voile": W_v1 + W_v2, "terres_talon": W_terre, "terres_patin": W_toe,
                  "surcharge_talon": W_q, "beche": W_key}, "PV": PgV + PqV, "U": U, "V": V, "Ms": Ms, "Mr": Mr,
            "H_total": PgH + PqH + Pw}


def stability(w: RetainingWall, g: dict) -> dict:
    phi_b = w.phi_base if w.phi_base is not None else w.soil.phi
    # renversement et glissement : surcharge sur le talon négligée (défavorable de ne pas la compter)
    a = _actions(w, g, with_q_on_heel=False)
    F_r = a["Ms"] / a["Mr"] if a["Mr"] else 99.0
    Bp = key_passive(w, g)["mobilisee"]
    F_g = (a["V"] * math.tan(math.radians(phi_b)) + Bp) / a["H_total"] if a["H_total"] else 99.0
    # contraintes sur le sol : surcharge sur le talon comptée
    b = _actions(w, g, with_q_on_heel=True)
    B = b["B"]
    x = (b["Ms"] - b["Mr"]) / b["V"]              # point de passage de la résultante
    e = B / 2 - x
    if abs(e) <= B / 6:
        qmax = b["V"] / B * (1 + 6 * e / B)
        qmin = b["V"] / B * (1 - 6 * e / B)
        q_ref = (3 * qmax + qmin) / 4
    else:                                         # sol partiellement décomprimé
        Lc = 3 * (B / 2 - abs(e))
        qmax = 2 * b["V"] / max(Lc, 1e-6)
        qmin = 0.0
        q_ref = 0.75 * qmax
    adm = w.sigma_sol * 1000
    return {"renversement": {"Fs": round(F_r, 2), "min": 1.5, "ok": F_r >= 1.5},
            "glissement": {"Fs": round(F_g, 2), "min": 1.5, "ok": F_g >= 1.5, "phi_base": phi_b,
                           "butee_beche_kN": round(Bp, 1)},
            "excentricite": {"e": round(e, 3), "limite": round(B / 6, 3), "ok": abs(e) <= B / 6},
            "sol": {"qmax_kPa": round(qmax, 1), "qmin_kPa": round(qmin, 1), "q_ref_kPa": round(q_ref, 1),
                    "q_adm_kPa": round(adm, 1), "ok": q_ref <= adm and qmax <= 1.33 * adm},
            "_actions": a, "_actions_sol": b, "_e": e, "_qmax": qmax, "_qmin": qmin}


def key_passive(w: RetainingWall, g: dict) -> dict:
    """Butée devant la bêche et la semelle (Rankine, sol de fondation), comptée à 50 % (déplacement limité).

    Profondeurs mesurées depuis le terrain côté aval : de la fiche (terre devant le patin) jusqu'au pied
    de la bêche. Le surcroît de contrainte apporté par le patin est négligé (sécurité).
    """
    kd = max(0.0, w.key_depth)
    if kd <= 0:
        return {"Kp": 0.0, "totale": 0.0, "mobilisee": 0.0, "beche": 0.0, "z1": 0.0, "z2": 0.0}
    phi_b = w.phi_base if w.phi_base is not None else w.soil.phi
    kp = 1 / ka_rankine(phi_b)
    gam = w.soil.gamma
    z2 = max(0.0, w.fiche) + g["h_base"] + kd
    z1 = max(0.0, w.fiche) + g["h_base"]
    Pp = 0.5 * kp * gam * z2 ** 2
    Pk = 0.5 * kp * gam * (z2 ** 2 - z1 ** 2)           # part reprise par la bêche seule
    return {"Kp": kp, "totale": Pp, "mobilisee": 0.5 * Pp, "beche": Pk, "z1": z1, "z2": z2}


def size_base(w: RetainingWall, notes: list[str]) -> dict:
    """Allonge le talon (puis le patin) jusqu'à satisfaire les quatre vérifications de stabilité."""
    g = predimension(w)
    fixed_heel, fixed_toe = w.heel is not None, w.toe is not None
    for _ in range(80):
        st = stability(w, g)
        if all(st[k]["ok"] for k in ("renversement", "glissement", "excentricite", "sol")):
            return g
        if not st["sol"]["ok"] and st["excentricite"]["ok"] and not fixed_toe:
            g["toe"] = round(g["toe"] + 0.05, 2)
        elif not fixed_heel:
            g["heel"] = round(g["heel"] + 0.05, 2)
            if not fixed_toe and g["toe"] < 0.25 * (g["toe"] + g["t_base"] + g["heel"]) - 0.05:
                g["toe"] = round(g["toe"] + 0.05, 2)
        elif not fixed_toe:
            g["toe"] = round(g["toe"] + 0.05, 2)
        else:
            break
    notes.append("Stabilité non obtenue avec la géométrie imposée : agrandir la semelle ou prévoir une bêche.")
    return g


# ------------------------------------------------------------------ béton armé
def bars_per_m(as_cm2: float, d_min: int = 10) -> tuple[int, float, float]:
    """Barres par mètre : (Ø mm, espacement m, section réelle cm²/m), e entre 10 et 25 cm."""
    for d in (10, 12, 14, 16, 20, 25):
        if d < d_min:
            continue
        s = math.floor(bar_area(d) / max(as_cm2, 1e-6) * 100 / 2.5) * 0.025   # pas de 2,5 cm
        s = min(s, 0.25)
        if s >= 0.10:
            return d, round(s, 3), round(bar_area(d) / s, 2)
    return 25, 0.10, round(bar_area(25) / 0.10, 2)


def _section(code, mu: float, vu: float, h: float, cover: float) -> dict:
    """Ferraillage d'une bande de 1 m (flexion simple) et vérification à l'effort tranchant."""
    a_s, a_c, notes = code.flexure(abs(mu), 1.0, h)
    d, s, a_real = bars_per_m(a_s)
    dd = h - cover - d / 2000
    tau = abs(vu) / 1000 / (1.0 * dd)               # MPa
    name = type(code).__name__.upper()
    if "EC2" in name or "EURO" in name:
        k = min(2.0, 1 + math.sqrt(0.2 / dd))
        tau_lim = 0.035 * k ** 1.5 * math.sqrt(code.fck) * 1.0
    else:
        tau_lim = 0.07 * code.fc28 / 1.5              # BAEL A.5.2.2 (dalles et voiles)
    return {"Mu_kNm": round(mu, 1), "Vu_kN": round(vu, 1), "h": h, "As_cm2_m": round(a_s, 2),
            "barres": f"HA{d} e={s * 100:.1f} cm".replace(".0 cm", " cm"), "d_mm": d, "e_m": s, "As_reel": a_real,
            "tau_MPa": round(tau, 3), "tau_lim_MPa": round(tau_lim, 3), "ok_cisaillement": tau <= tau_lim,
            "notes": notes}


def reinforcement(w: RetainingWall, g: dict, code, st: dict) -> dict:
    H, s = w.height, w.soil
    ka = st["_actions"]["ka"]
    # --- voile (encastré dans la semelle) : poussée sur la hauteur H du voile
    PgH = 0.5 * ka * s.gamma * H ** 2
    PqH = ka * w.surcharge * H
    Mw = 1.35 * PgH * H / 3 + 1.5 * PqH * H / 2
    Vw = 1.35 * PgH + 1.5 * PqH
    if w.water is not None and w.water < H:
        hw = H - w.water
        Mw += 1.35 * 0.5 * GAMMA_W * hw ** 2 * hw / 3
        Vw += 1.35 * 0.5 * GAMMA_W * hw ** 2
    voile = _section(code, Mw, Vw, g["t_base"], w.cover)
    # --- contraintes sous la semelle à l'ELU (même répartition, majorée par le rapport ELU/ELS)
    b = st["_actions_sol"]
    B = b["B"]
    ratio = (1.35 * (b["PgH"] + b["Pw"]) + 1.5 * b["PqH"]) / max(b["H_total"], 1e-6)
    ratio = max(1.35, ratio)
    qmax, qmin = st["_qmax"] * ratio, st["_qmin"] * ratio
    e = st["_e"]
    full = abs(e) <= B / 6

    def q_at(x):                                  # x depuis l'arête avant du patin
        if full:
            return qmax + (qmin - qmax) * x / B if e >= 0 else qmin + (qmax - qmin) * x / B
        Lc = 3 * (B / 2 - abs(e))
        return max(0.0, qmax * (1 - x / Lc)) if e >= 0 else max(0.0, qmax * (1 - (B - x) / Lc))

    hb, toe, heel, tb = g["h_base"], g["toe"], g["heel"], g["t_base"]
    # patin : sol vers le haut − poids propre (et terres devant), moment à la jonction avec le voile
    n = 40
    Mt = Vt = 0.0
    for i in range(n):
        x = (i + 0.5) * toe / n
        net = q_at(x) - 1.35 * (GAMMA_BA * hb + s.gamma * max(0.0, w.fiche))
        Mt += net * toe / n * (toe - x)
        Vt += net * toe / n
    patin = _section(code, max(Mt, 0.0), max(Vt, 0.0), hb, w.cover)
    # talon : terres + surcharge + poids propre vers le bas − sol, moment à la jonction
    Mh = Vh = 0.0
    load = 1.35 * (GAMMA_BA * hb + s.gamma * H) + 1.5 * w.surcharge
    for i in range(n):
        x = toe + tb + (i + 0.5) * heel / n
        net = load - q_at(x)
        Mh += net * heel / n * (x - toe - tb)
        Vh += net * heel / n
    talon = _section(code, max(Mh, 0.0), max(Vh, 0.0), hb, w.cover)
    # armatures de répartition et de peau (≥ 1/4 des principales, ≥ HA8 e = 20 cm)
    def rep(main):
        a = max(main["As_reel"] / 4, bar_area(8) / 0.20)
        d, s_, ar = bars_per_m(a, d_min=8)
        return f"HA{d} e={s_ * 100:.0f} cm", ar
    for part in (voile, patin, talon):
        part["repartition"], part["As_rep"] = rep(part)
    voile["face_avant"] = "HA8 e=20 cm (vertical et horizontal)"
    out = {"voile": voile, "patin": patin, "talon": talon, "q_elu_kPa": [round(qmax, 1), round(qmin, 1)]}
    if w.key_depth > 0:                         # bêche : console encastrée sous la semelle, butée totale × 1,35
        kp = key_passive(w, g)
        z1, z2, gam = kp["z1"], kp["z2"], s.gamma
        p1, p2 = kp["Kp"] * gam * z1, kp["Kp"] * gam * z2
        kd = w.key_depth
        Vk = 1.35 * kp["beche"]
        Mk = 1.35 * (p1 * kd ** 2 / 2 + (p2 - p1) * kd ** 2 / 6)
        bk = _section(code, Mk, Vk, w.key_width, w.cover)
        bmin = bar_area(10) / 0.20
        if bk["As_reel"] < bmin:
            bk.update(barres="HA10 e=20 cm", d_mm=10, e_m=0.20, As_reel=round(bmin, 2))
        bk["repartition"], bk["As_rep"] = "4 HA10 filants", round(4 * bar_area(10), 2)
        out["beche"] = bk
    return out


def quantities(w: RetainingWall, g: dict, ra: dict) -> dict:
    H, L = w.height, w.length
    hb, toe, heel, tt, tb = g["h_base"], g["toe"], g["heel"], g["t_top"], g["t_base"]
    B = toe + tb + heel
    v_voile = 0.5 * (tt + tb) * H
    v_sem = B * hb
    # acier : barres principales + répartition, recouvrements et ancrages ≈ +15 %
    def kg(part, span):
        d, s = part["d_mm"], part["e_m"]
        main = (1 / s) * span * bar_mass(d)
        rep_d = int(part["repartition"].split()[0][2:])
        rep_s = float(part["repartition"].split("=")[1].split()[0]) / 100
        rep = (1 / rep_s) * 1.0 * bar_mass(rep_d) * span
        return main + rep
    steel = 1.15 * (kg(ra["voile"], H + 0.6 * hb + 0.5) + kg(ra["talon"], heel + tb) + kg(ra["patin"], toe + tb)
                    + 2 * (1 / 0.20) * bar_mass(8) * H)                  # face avant HA8 e = 20 cm
    v_key = max(0.0, w.key_depth) * w.key_width
    if v_key:
        steel += 1.15 * ((1 / 0.20) * bar_mass(10) * (2 * (w.key_depth + hb) + w.key_width) + 4 * bar_mass(10))
    per_ml = {"beton_m3": v_voile + v_sem + v_key, "beton_voile_m3": v_voile, "beton_semelle_m3": v_sem + v_key,
              "beton_proprete_m3": 0.05 * (B + 0.2), "acier_kg": steel,
              "coffrage_m2": 2 * H + 2 * hb, "fouille_m3": (B + 0.6) * (hb + 0.05 + max(0.0, w.fiche) + 0.3) + v_key,
              "remblai_drainant_m3": 0.40 * H, "drain_ml": 1.0, "geotextile_m2": H + 0.6,
              "barbacanes_u": 0.5, "enduit_bitumineux_m2": H + hb}
    total = {k: round(v * L, 2) for k, v in per_ml.items()}
    total["barbacanes_u"] = math.ceil(per_ml["barbacanes_u"] * L)
    return {"par_ml": {k: round(v, 3) for k, v in per_ml.items()}, "total": total, "longueur": L,
            "ratio_acier_kg_m3": round(steel / (v_voile + v_sem + v_key), 0)}


def design_wall(w: RetainingWall, code) -> WallResult:
    notes: list[str] = []
    if w.slope > w.soil.phi:
        raise ValueError(f"Pente du talus β = {w.slope}° supérieure à φ = {w.soil.phi}° : talus instable.")
    if w.height > 6.0:
        notes.append("Hauteur > 6 m : un mur à contreforts ou une paroi ancrée est à comparer au mur cantilever.")
    g = size_base(w, notes)
    st = stability(w, g)
    ra = reinforcement(w, g, code, st)
    for k in [k for k in ("voile", "patin", "talon", "beche") if k in ra]:
        if not ra[k]["ok_cisaillement"]:
            notes.append(f"{k.capitalize()} : τu = {ra[k]['tau_MPa']} MPa > {ra[k]['tau_lim_MPa']} MPa : épaissir la section.")
        notes += [f"{k.capitalize()} : {n}" for n in ra[k]["notes"]]
    if w.water is not None:
        notes.append("Nappe prise en compte derrière le mur : poussée hydrostatique et sous-pression ; "
                     "un drainage efficace (barbacanes, drain, remblai drainant) réduirait fortement les efforts.")
    else:
        notes.append("Mur drainé : barbacanes Ø 100 tous les 2 m, drain en pied et remblai drainant derrière le voile "
                     "(hypothèse du calcul sans pression d'eau).")
    q = quantities(w, g, ra)
    ok = all(st[k]["ok"] for k in ("renversement", "glissement", "excentricite", "sol")) and \
        all(ra[k]["ok_cisaillement"] for k in ("voile", "patin", "talon", "beche") if k in ra)
    a = st["_actions"]
    forces = {"poussee_terres_kN_ml": round(a["PgH"], 1), "poussee_surcharge_kN_ml": round(a["PqH"], 1),
              "poussee_eau_kN_ml": round(a["Pw"], 1), "sous_pression_kN_ml": round(a["U"], 1),
              "hauteur_ecran_fictif_m": round(a["Hv"], 2), "poids_kN_ml": {k: round(v, 1) for k, v in a["W"].items()},
              "V_kN_ml": round(a["V"], 1), "M_stabilisant_kNm_ml": round(a["Ms"], 1),
              "M_renversant_kNm_ml": round(a["Mr"], 1)}
    stab = {k: v for k, v in st.items() if not k.startswith("_")}
    geom = dict(g, B=round(g["toe"] + g["t_base"] + g["heel"], 2), hauteur_totale=round(w.height + g["h_base"], 2),
                key_depth=round(max(0.0, w.key_depth), 2), key_width=round(w.key_width, 2) if w.key_depth > 0 else 0.0)
    if w.key_depth > 0:
        notes.append(f"Bêche {w.key_width * 100:.0f} × {w.key_depth * 100:.0f} cm sous le voile, coulée à pleine fouille "
                     f"contre le sol en place : butée comptée à 50 % ({st['glissement']['butee_beche_kN']} kN/ml).")
    return WallResult(asdict(w), geom, round(a["ka"], 3), forces, stab, ra, q, ok, notes)


# ------------------------------------------------------------------ sorties
def wall_dxf(res: WallResult, path) -> None:
    """Coupe type du mur avec cotes et ferraillage."""
    import ezdxf

    g, w = res.geometry, res.wall
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for name, color in (("BETON", 7), ("ACIERS", 1), ("TERRE", 8), ("COTES", 3), ("TEXTES", 7)):
        doc.layers.add(name, color=color)
    m = doc.modelspace()
    toe, tb, tt, heel, hb, H = g["toe"], g["t_base"], g["t_top"], g["heel"], g["h_base"], w["height"]
    B = toe + tb + heel
    kd, kw = g.get("key_depth", 0.0), g.get("key_width", 0.0)
    xk = toe + tb
    bottom = [(xk - kw, 0), (xk - kw, -kd), (xk, -kd), (xk, 0)] if kd > 0 else []
    m.add_lwpolyline([(0, 0), *bottom, (B, 0), (B, hb), (toe + tb, hb), (toe + tb, hb + H), (toe + tb - tt, hb + H),
                      (toe, hb), (0, hb)], close=True, dxfattribs={"layer": "BETON"})
    m.add_lwpolyline([(-0.1, -0.05), (B + 0.1, -0.05)], dxfattribs={"layer": "BETON"})
    if kd > 0:
        m.add_linear_dim(base=(xk + 0.25, 0), p1=(xk, 0), p2=(xk, -kd), angle=90, dxfattribs={"layer": "COTES"},
                         override={"dimtxt": 0.07, "dimasz": 0.05, "dimdec": 2, "dimzin": 8}).render()
    m.add_line((toe + tb, hb + H), (B + 1.5, hb + H + 1.5 * math.tan(math.radians(w["slope"]))), dxfattribs={"layer": "TERRE"})
    if w["fiche"] > 0:
        m.add_line((-1.0, hb + w["fiche"]), (toe, hb + w["fiche"]), dxfattribs={"layer": "TERRE"})
    c = w["cover"]
    ra = res.reinforcement
    A = {"layer": "ACIERS"}
    xb = toe + tb - c                                          # aciers verticaux côté terres
    m.add_lwpolyline([(xb - 0.35, c + 0.02), (xb, c + 0.02), (xb, hb + H - c)], dxfattribs=A)
    xf = toe + c                                               # aciers de la face avant (suivent le fruit)
    m.add_line((xf, c + 0.02), (toe + tb - tt + c, hb + H - c), dxfattribs=A)
    m.add_lwpolyline([(c, hb - c - 0.10), (c, hb - c), (B - c, hb - c), (B - c, hb - c - 0.10)], dxfattribs=A)   # nappe sup.
    m.add_lwpolyline([(c, c + 0.10), (c, c), (B - c, c), (B - c, c + 0.10)], dxfattribs=A)                    # nappe inf.
    t = lambda s_, x, y, h=0.08: m.add_text(s_, height=h, dxfattribs={"layer": "TEXTES", "insert": (x, y)})  # noqa: E731
    # repères sur le dessin, légende dessous
    for k, (x, y) in enumerate(((xb + 0.08, hb + 0.6 * H), (xf - 0.25, hb + 0.4 * H), (B - 0.35, hb - c + 0.04),
                                (0.15, c + 0.04)), start=1):
        t(str(k), x, y, 0.10)
    leg = [f"1 — Voile côté terres : {ra['voile']['barres']} vertical, répartition {ra['voile']['repartition']}",
           f"2 — Voile face avant : {ra['voile']['face_avant']}",
           f"3 — Semelle, nappe supérieure (talon) : {ra['talon']['barres']}, répartition {ra['talon']['repartition']}",
           f"4 — Semelle, nappe inférieure (patin) : {ra['patin']['barres']}, répartition {ra['patin']['repartition']}",
           f"Enrobage {c * 100:.0f} cm · béton dosé à 350 kg/m³ · béton de propreté 5 cm · barbacanes Ø 100 tous les 2 m, "
           "drain et remblai drainant"]
    for k, line in enumerate(leg):
        t(line, 0, -0.85 - 0.16 * k, 0.07)
    t("COUPE TYPE — MUR DE SOUTÈNEMENT", 0, hb + H + 0.45, 0.13)
    dim = dict(dxfattribs={"layer": "COTES"},
               override={"dimtxt": 0.07, "dimasz": 0.05, "dimdec": 2, "dimlfac": 1.0, "dimexe": 0.05, "dimexo": 0.05, "dimzin": 8})
    m.add_linear_dim(base=(0, -0.55), p1=(0, 0), p2=(B, 0), **dim).render()
    m.add_linear_dim(base=(0, -0.32), p1=(0, 0), p2=(toe, 0), **dim).render()
    m.add_linear_dim(base=(0, -0.32), p1=(toe, 0), p2=(toe + tb, 0), **dim).render()
    m.add_linear_dim(base=(0, -0.32), p1=(toe + tb, 0), p2=(B, 0), **dim).render()
    m.add_linear_dim(base=(B + 0.30, 0), p1=(B, 0), p2=(B, hb), angle=90, **dim).render()
    m.add_linear_dim(base=(toe + tb + 0.45, 0), p1=(toe + tb, hb), p2=(toe + tb, hb + H), angle=90, **dim).render()
    m.add_linear_dim(base=(0, hb + H + 0.20), p1=(toe + tb - tt, hb + H), p2=(toe + tb, hb + H), **dim).render()
    doc.saveas(path)


def wall_html(res: WallResult, code) -> str:
    g, w, st, ra, q = res.geometry, res.wall, res.stability, res.reinforcement, res.quantities
    ok = lambda b: '<b style="color:#1d7f46">vérifié</b>' if b else '<b style="color:#b42318">NON vérifié</b>'  # noqa: E731
    f = lambda v, n=2: f"{v:,.{n}f}".replace(",", " ").replace(".", ",")  # noqa: E731
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in (
        ("Hauteur de terres retenues (voile)", f"{f(w['height'])} m"), ("Longueur du mur", f"{f(w['length'])} m"),
        ("Surcharge sur le terre-plein", f"{f(w['surcharge'], 1)} kN/m²"), ("Pente du terre-plein β", f"{f(w['slope'], 0)}°"),
        ("Remblai : γ / φ", f"{f(w['soil']['gamma'], 1)} kN/m³ / {f(w['soil']['phi'], 0)}°"),
        ("Contrainte admissible du sol (ELS)", f"{f(w['sigma_sol'], 3)} MPa"),
        ("Nappe derrière le mur", "non (mur drainé)" if w["water"] is None else f"à {f(w['water'])} m sous le haut du remblai")))
    geo = "".join(f"<tr><td>{k}</td><td>{f(v)} m</td></tr>" for k, v in (
        ("Épaisseur du voile en tête", g["t_top"]), ("Épaisseur du voile en pied", g["t_base"]),
        ("Épaisseur de la semelle", g["h_base"]), ("Patin (avant)", g["toe"]), ("Talon (arrière)", g["heel"]),
        ("Largeur de la semelle B", g["B"]), ("Hauteur totale", g["hauteur_totale"]))
        + ((("Bêche sous le voile : largeur", g["key_width"]), ("Bêche : hauteur sous la semelle", g["key_depth"]))
           if g.get("key_depth") else ()))
    stab = (f"<tr><td>Renversement</td><td>Fs = {f(st['renversement']['Fs'])} ≥ 1,5</td><td>{ok(st['renversement']['ok'])}</td></tr>"
            f"<tr><td>Glissement (φ base = {f(st['glissement']['phi_base'], 0)}°, "
            + (f"butée devant la bêche comptée à 50 % : {f(st['glissement']['butee_beche_kN'], 1)} kN/ml)</td>"
               if st['glissement'].get('butee_beche_kN') else "butée négligée)</td>")
            + f"<td>Fs = {f(st['glissement']['Fs'])} ≥ 1,5</td><td>{ok(st['glissement']['ok'])}</td></tr>"
            f"<tr><td>Excentricité de la résultante</td><td>e = {f(st['excentricite']['e'], 3)} m ≤ B/6 = "
            f"{f(st['excentricite']['limite'], 3)} m</td><td>{ok(st['excentricite']['ok'])}</td></tr>"
            f"<tr><td>Contrainte sur le sol</td><td>q réf = (3 qmax + qmin)/4 = {f(st['sol']['q_ref_kPa'], 1)} kPa ≤ "
            f"{f(st['sol']['q_adm_kPa'], 1)} kPa (qmax = {f(st['sol']['qmax_kPa'], 1)}, qmin = {f(st['sol']['qmin_kPa'], 1)})</td>"
            f"<td>{ok(st['sol']['ok'])}</td></tr>")
    ba = "".join(f"<tr><td>{n}</td><td>{f(p['Mu_kNm'], 1)}</td><td>{f(p['Vu_kN'], 1)}</td><td>{f(p['As_cm2_m'])}</td>"
                 f"<td>{p['barres']}</td><td>{p['repartition']}</td><td>{f(p['tau_MPa'], 3)} ≤ {f(p['tau_lim_MPa'], 3)} "
                 f"{ok(p['ok_cisaillement'])}</td></tr>" for n, p in (("Voile (pied, côté terres)", ra["voile"]),
                                                                       ("Talon (nappe supérieure)", ra["talon"]),
                                                                       ("Patin (nappe inférieure)", ra["patin"]))
                 + ((("Bêche (face aval)", ra["beche"]),) if "beche" in ra else ()))
    qt = q["total"]
    met = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in (
        ("Béton armé dosé à 350 kg/m³", f"{f(qt['beton_m3'])} m³ (voile {f(qt['beton_voile_m3'])}, semelle {f(qt['beton_semelle_m3'])})"),
        ("Béton de propreté", f"{f(qt['beton_proprete_m3'])} m³"), ("Acier HA", f"{f(qt['acier_kg'], 0)} kg ({f(q['ratio_acier_kg_m3'], 0)} kg/m³)"),
        ("Coffrage", f"{f(qt['coffrage_m2'], 1)} m²"), ("Fouilles", f"{f(qt['fouille_m3'], 1)} m³"),
        ("Remblai drainant", f"{f(qt['remblai_drainant_m3'], 1)} m³"), ("Drain Ø 100 en pied", f"{f(qt['drain_ml'], 1)} ml"),
        ("Géotextile", f"{f(qt['geotextile_m2'], 1)} m²"), ("Barbacanes Ø 100", f"{qt['barbacanes_u']} u"),
        ("Enduit bitumineux (parement enterré)", f"{f(qt['enduit_bitumineux_m2'], 1)} m²")))
    notes = "".join(f"<li>{n}</li>" for n in res.notes)
    return f"""<!doctype html><html lang=fr><head><meta charset=utf-8><title>Mur de soutènement</title><style>
body {{ font: 10pt/1.45 "DejaVu Sans", Arial, sans-serif; color:#1c2430; max-width: 900px; margin: 20px auto; }}
h1 {{ color:#1f4e79; font-size:16pt }} h2 {{ color:#1f4e79; font-size:12pt; border-bottom:2px solid #1f4e79; margin-top:18px }}
table {{ border-collapse:collapse; width:100%; margin:6px 0 }} td, th {{ border:1px solid #9aa8b7; padding:4px 6px; vertical-align:top }}
th {{ background:#1f4e79; color:#fff; text-align:left }}</style></head><body>
<h1>NOTE DE CALCUL — MUR DE SOUTÈNEMENT EN BÉTON ARMÉ</h1>
<p>Mur cantilever en T renversé, calcul par mètre linéaire. Règlement : {"Eurocode 2 (NF EN 1992-1-1)" if hasattr(code, "fck") else "BAEL 91 mod. 99"} — {"fck" if hasattr(code, "fck") else "fc28"} = {getattr(code, "fck", getattr(code, "fc28", 25)):g} MPa, acier {getattr(code, "fyk", getattr(code, "fe", 400)):g} MPa.
Résultat global : {ok(res.ok)}.</p>
<h2>1. Données</h2><table>{rows}</table>
<h2>2. Géométrie retenue</h2><table>{geo}</table>
<h2>3. Poussées (Rankine, Ka = {f(res.ka, 3)}, écran fictif de {f(res.forces['hauteur_ecran_fictif_m'])} m)</h2>
<table><tr><td>Poussée des terres</td><td>{f(res.forces['poussee_terres_kN_ml'], 1)} kN/ml</td></tr>
<tr><td>Poussée due à la surcharge</td><td>{f(res.forces['poussee_surcharge_kN_ml'], 1)} kN/ml</td></tr>
<tr><td>Poussée de l'eau / sous-pression</td><td>{f(res.forces['poussee_eau_kN_ml'], 1)} / {f(res.forces['sous_pression_kN_ml'], 1)} kN/ml</td></tr>
<tr><td>Effort vertical total / moments stabilisant et renversant</td><td>{f(res.forces['V_kN_ml'], 1)} kN/ml ; {f(res.forces['M_stabilisant_kNm_ml'], 1)} / {f(res.forces['M_renversant_kNm_ml'], 1)} kN·m/ml</td></tr></table>
<h2>4. Stabilité externe</h2><table><tr><th>Vérification</th><th>Valeur</th><th>Résultat</th></tr>{stab}</table>
<h2>5. Ferraillage (ELU 1,35 G + 1,5 Q, par mètre)</h2>
<table><tr><th>Élément</th><th>Mu (kN·m)</th><th>Vu (kN)</th><th>As (cm²/m)</th><th>Aciers principaux</th><th>Répartition</th><th>Cisaillement τu (MPa)</th></tr>{ba}</table>
<p>Face avant du voile : {ra['voile']['face_avant']}. Enrobage {f(w['cover'] * 100, 0)} cm côté terres.</p>
<h2>6. Métré ({f(q['longueur'], 1)} ml)</h2><table>{met}</table>
<h2>7. Remarques</h2><ul>{notes}</ul></body></html>"""
