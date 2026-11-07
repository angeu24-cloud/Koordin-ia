"""Assainissement autonome : bac à graisses, fosse toutes eaux, puits d'infiltration (puits perdu)
ou autre filière d'infiltration selon le sol.

Méthode (pré-dimensionnement d'avant-projet, à valider par essai de sol) :
- fosse : volume = max(minimum réglementaire, volume hydraulique + stockage des boues),
  - minimum réglementaire de type DTU 64.1 : 3 m³ jusqu'à 5 pièces principales, + 1 m³ par pièce
    supplémentaire ;
  - volume hydraulique : usagers × dotation × temps de séjour ;
  - boues : usagers × taux d'accumulation × intervalle de vidange ;
  - deux compartiments (≈ 2/3 – 1/3), rapport longueur / largeur de 2 à 3 ;
- puits : surface de paroi infiltrante = débit de projet / charge hydraulique admissible du sol
  (fond non compté, colmatage) ;
- en sol peu perméable (< 20 L/m²/j) ou nappe haute : puits déconseillé → épandage ou filtre à
  sable drainé.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

# charge hydraulique admissible durable sur la paroi d'un puits (effluent de fosse), L/m²/jour
# valeurs usuelles de pré-dimensionnement, à confirmer par un essai de percolation sur site
SOLS: dict[str, dict] = {
    "gravier": {"nom": "Gravier, sable grossier", "charge": 50, "note": "très perméable : protéger la nappe "
                "(couche filtrante de sable 0,30 m en paroi)"},
    "sable": {"nom": "Sable moyen à fin", "charge": 50, "note": ""},
    "sable_limoneux": {"nom": "Sable limoneux, latérite sableuse", "charge": 30, "note": ""},
    "limon": {"nom": "Limon, latérite limoneuse", "charge": 20, "note": "puits possible mais volumineux"},
    "argile": {"nom": "Argile, latérite argileuse compacte", "charge": 8, "note": "puits déconseillé"},
}


def _up(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 3)


@dataclass
class Fosse:
    usagers: int
    pieces: int | None
    debit_m3j: float
    v_reglementaire: float
    v_hydraulique: float
    v_boues: float
    v_requis: float
    v_adopte: float
    largeur: float           # intérieure (m)
    longueur_1: float        # compartiment 1 (m)
    longueur_2: float        # compartiment 2 (m)
    hauteur_eau: float
    garde_air: float
    voile: float
    cloison: float
    radier: float
    dalle: float
    ext_longueur: float = 0.0
    ext_largeur: float = 0.0
    ext_hauteur: float = 0.0
    beton_m3: float = 0.0
    acier_kg: float = 0.0
    vidange_ans: float = 0.0
    armatures: dict = field(default_factory=dict)
    verifications: list[str] = field(default_factory=list)

    @property
    def longueur(self) -> float:
        return round(self.longueur_1 + self.longueur_2, 3)

    @property
    def v_utile(self) -> float:
        return round(self.longueur * self.largeur * self.hauteur_eau, 3)


def fosse_toutes_eaux(usagers: int, pieces: int | None = None, dotation_l: float = 150.0, sejour_j: float = 2.0,
                      boues_m3_an: float = 0.04, vidange_ans: float = 2.0, hauteur_eau: float = 1.50,
                      v_min_adopte: float = 0.0, profondeur_terre: float = 0.30, surcharge_kpa: float = 5.0,
                      gamma_sol: float = 18.0, k0: float = 0.5, fe: float = 400.0, fc28: float = 25.0) -> Fosse:
    q = usagers * dotation_l / 1000
    v_reg = 3.0 + max(0, (pieces or 0) - 5) * 1.0 if pieces else 3.0
    v_h = q * sejour_j
    v_b = usagers * boues_m3_an * vidange_ans
    v_req = max(v_reg, v_h + v_b)
    v_ad = max(_up(v_req, 0.5), v_min_adopte)
    area = v_ad / hauteur_eau
    w = _up(math.sqrt(area / 2.1), 0.05)
    L = _up(area / w, 0.05)
    l1 = _up(L * 2 / 3, 0.05)
    l2 = round(L - l1, 3)
    f = Fosse(usagers, pieces, round(q, 3), v_reg, round(v_h, 3), round(v_b, 3), round(v_req, 3), v_ad, w, l1, l2,
              hauteur_eau, 0.25, 0.20, 0.15, 0.20, 0.15)
    h_int = hauteur_eau + f.garde_air
    f.ext_longueur = round(l1 + l2 + f.cloison + 2 * f.voile, 3)
    f.ext_largeur = round(w + 2 * f.voile, 3)
    f.ext_hauteur = round(h_int + f.radier + f.dalle, 3)
    v_ext = f.ext_longueur * f.ext_largeur * f.ext_hauteur
    v_int = (l1 + l2 + f.cloison) * w * h_int
    f.beton_m3 = round(v_ext - v_int + f.cloison * w * h_int - 2 * 0.6 * 0.6 * f.dalle, 2)
    # armatures : voiles en appui radier / dalle (poussée des terres au repos + surcharge), fissuration
    # très préjudiciable (ouvrage étanche) : σs = 0,8 × max(0,5 fe ; 110 √(η ft28)) borné à 2/3 fe
    ft28 = 0.6 + 0.06 * fc28
    sig_s = 0.8 * min(2 / 3 * fe, max(0.5 * fe, 110 * math.sqrt(1.6 * ft28)))
    H = f.ext_hauteur + profondeur_terre
    p_t = k0 * gamma_sol * H
    m_ser = p_t * h_int ** 2 / 15 + k0 * surcharge_kpa * h_int ** 2 / 8      # kN.m/m
    d = f.voile - 0.05
    as_calc = m_ser * 1e-3 / (0.9 * d * sig_s) * 1e4                         # cm²/m
    as_min = 0.0025 * f.voile * 1e4 / 2                                      # par face (0,25 % total)
    as_face = max(as_calc, as_min)
    bars = next((f"HA{db} e={e} cm" for db in (10, 12) for e in (20, 15, 12.5, 10)
                 if math.pi * (db / 20) ** 2 * 100 / e >= as_face and e >= 10), "HA12 e=10 cm")
    if as_face <= math.pi * 0.5 ** 2 * 100 / 15:
        bars = "HA10 e=15 cm"   # espacement maximal retenu pour la maîtrise de la fissuration
    f.armatures = {"voiles": f"{bars}, 2 faces, 2 directions", "radier": f"{bars}, 2 nappes",
                   "dalle": "HA10 e=15 cm, 2 directions (hors circulation de véhicules)",
                   "trappes": "2 HA12 de renfort de chaque côté des trémies 0,60 × 0,60",
                   "M_ser_voile_kNm_m": round(m_ser, 2), "As_calcul_cm2_m": round(as_calc, 2),
                   "As_min_cm2_m": round(as_min, 2), "sigma_s_MPa": round(sig_s, 0)}
    f.acier_kg = round(f.beton_m3 * 90, 0)
    stock = max(0.0, v_ad * 0.5)            # vidange quand les boues atteignent ~50 % du volume
    # intervalle théorique, plafonné à 4 ans (contrôle des boues et flottants recommandé)
    f.vidange_ans = min(4.0, round(stock / (usagers * boues_m3_an), 1)) if usagers else 0.0
    f.verifications = [
        f"Volume réglementaire minimal : {v_reg:.1f} m³" + (f" ({pieces} pièces principales)" if pieces else ""),
        f"Volume hydraulique : {usagers} usagers × {dotation_l:.0f} L × {sejour_j:g} j = {v_h:.2f} m³",
        f"Stockage des boues : {usagers} × {boues_m3_an:g} m³/an × {vidange_ans:g} ans = {v_b:.2f} m³",
        f"Volume requis : {v_req:.2f} m³ → adopté {v_ad:.2f} m³ ({f.v_utile:.2f} m³ utiles)",
        f"Rapport longueur / largeur : {f.longueur / w:.2f} (2 à 3 recommandé)",
        f"Compartiment 1 : {l1 / (l1 + l2) * 100:.0f} % du volume (≈ 2/3 recommandé)",
    ]
    return f


@dataclass
class PuitsOption:
    diametre: float          # intérieur (m)
    hauteur_active: float    # hauteur de paroi infiltrante (m)
    nombre: int
    surface_m2: float
    fouille_m3: float
    profondeur_fond: float   # sous le fil d'eau d'arrivée (m)


@dataclass
class Infiltration:
    sol: str
    charge_l_m2j: float
    debit_projet_m3j: float
    surface_requise_m2: float
    filiere: str
    options: list[PuitsOption] = field(default_factory=list)
    recommandee: PuitsOption | None = None
    notes: list[str] = field(default_factory=list)


def infiltration(debit_m3j: float, sol: str | None = None, charge_l_m2j: float | None = None,
                 securite: float = 1.25, diametres=(1.5, 2.0, 2.5), h_max: float = 4.0, h_min: float = 1.5,
                 tete: float = 0.70, gravier: float = 0.30, couronne: float = 0.30, paroi: float = 0.15) -> Infiltration:
    if charge_l_m2j is None:
        charge_l_m2j = SOLS[sol or "sable_limoneux"]["charge"]
    q = debit_m3j * securite
    A = q * 1000 / charge_l_m2j
    res = Infiltration(sol or "essai", charge_l_m2j, round(q, 3), round(A, 1), "puits d'infiltration")
    if charge_l_m2j < 15:
        res.filiere = "épandage ou filtre à sable drainé"
        res.notes.append(f"Charge admissible {charge_l_m2j:g} L/m²/j < 15 : puits perdu déconseillé. Prévoir des "
                         f"tranchées d'épandage (≈ {A:.0f} m² de fond de tranchée) ou un filtre à sable vertical "
                         "drainé avec rejet.")
        return res
    for D in diametres:
        for n in (1, 2, 3):
            h = _up(A / (n * math.pi * D), 0.1)
            if h > h_max:
                continue
            h = max(h, h_min)
            r_f = D / 2 + paroi + couronne
            depth = tete + h + gravier
            res.options.append(PuitsOption(D, h, n, round(n * math.pi * D * h, 1),
                                           round(n * math.pi * r_f ** 2 * (depth + 0.15), 1), round(depth, 2)))
            break
    if res.options:
        res.recommandee = min(res.options, key=lambda o: (o.nombre, o.fouille_m3))
    else:
        res.filiere = "épandage ou filtre à sable drainé"
    res.notes.append(f"Surface de paroi requise : {q:.3f} m³/j ÷ {charge_l_m2j:g} L/m²/j = {A:.1f} m² (fond non compté).")
    return res


def bac_graisses(cuisine_seule: bool = True, distance_fosse_m: float = 0.0) -> dict:
    """Bac dégraisseur : recommandé si la cuisine est à plus de 10 m de la fosse (DTU 64.1)."""
    need = distance_fosse_m > 10
    return {"necessaire": need, "volume_l": 200 if cuisine_seule else 500,
            "motif": f"cuisine à {distance_fosse_m:.0f} m de la fosse" + (" (> 10 m)" if need else "")}


def resume(f: Fosse, inf: Infiltration) -> dict:
    return {"fosse": asdict(f) | {"longueur": f.longueur, "v_utile": f.v_utile}, "infiltration": asdict(inf)}
