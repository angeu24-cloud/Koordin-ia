"""Éléments communs aux règlements : résultats, choix des armatures."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

BAR_DIAMETERS = [8, 10, 12, 14, 16, 20, 25, 32]  # mm


def bar_area(d_mm: float) -> float:
    """Section d'une barre en cm²."""
    return math.pi * (d_mm / 10) ** 2 / 4


def bar_mass(d_mm: float) -> float:
    """Masse linéique en kg/m (acier 7850 kg/m³)."""
    return 0.00617 * d_mm ** 2


@dataclass
class Bars:
    n: int
    d: int  # mm

    @property
    def area(self) -> float:
        return self.n * bar_area(self.d)

    def __str__(self) -> str:
        return f"{self.n}HA{self.d}"


def choose_bars(
    as_cm2: float,
    *,
    n_min: int = 2,
    n_max: int = 12,
    d_min: int = 10,
    d_max: int = 32,
    even: bool = False,
) -> Bars | None:
    """Plus petite section réelle couvrant As ; à section égale, le moins de barres."""
    best: Bars | None = None
    for d in BAR_DIAMETERS:
        if d < d_min or d > d_max:
            continue
        n = max(n_min, math.ceil(as_cm2 / bar_area(d) - 1e-9))
        if even and n % 2:
            n += 1
        if n > n_max:
            continue
        cand = Bars(n, d)
        if best is None or (cand.area, cand.n) < (best.area - 1e-9, best.n):
            best = cand
    return best


@dataclass
class Stirrups:
    d: int      # mm
    s: float    # espacement (m)
    legs: int = 2

    def __str__(self) -> str:
        return f"Cadre HA{self.d} e={self.s * 100:.0f} cm"


@dataclass
class ColumnDesign:
    b: float
    h: float
    nu: float          # kN
    as_req: float      # cm²
    as_min: float
    as_max: float
    bars: Bars | None
    stirrups: Stirrups | None
    slenderness: float
    ok: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class BeamDesign:
    b: float
    h: float
    mu_span: float     # kN.m
    mu_support: float  # kN.m
    vu: float          # kN
    as_span: float     # cm²
    as_support: float
    as_comp: float     # aciers comprimés éventuels
    bars_bottom: Bars | None
    bars_top: Bars | None
    stirrups: Stirrups | None
    ok: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class FootingDesign:
    A: float           # dimension selon X (m)
    B: float           # dimension selon Y (m)
    h: float           # hauteur (m)
    nser: float        # kN (y compris poids propre)
    nu: float
    as_x: float        # cm² (barres parallèles à A)
    as_y: float
    bars_x: Bars | None
    bars_y: Bars | None
    ok: bool
    notes: list[str] = field(default_factory=list)


def round_up(v: float, step: float = 0.05) -> float:
    return round(math.ceil(v / step - 1e-9) * step, 3)


def stirrup_spacing(asw_s_cm2_per_m: float, d: int, legs: int, s_max: float) -> float:
    """Espacement (m) pour obtenir Asw/s requis, arrondi au cm inférieur et plafonné."""
    asw = legs * bar_area(d)  # cm²
    s = s_max if asw_s_cm2_per_m <= 0 else min(s_max, asw / asw_s_cm2_per_m)
    return max(0.05, math.floor(s * 100) / 100)


def footing_design(
    a: float, b: float, nser_col: float, nu_col: float, sigma_sol: float, fsu: float,
    *, cover: float = 0.05,
) -> FootingDesign:
    """Semelle isolée sous poteau, méthode des bielles (BAEL / pratique EC2).

    a, b : dimensions du poteau (m) ; nser_col, nu_col (kN) ; sigma_sol (MPa) ; fsu (MPa).
    """
    notes: list[str] = []
    q_sol = sigma_sol * 1000  # kPa = kN/m²
    nser, nu = nser_col, nu_col
    A = B = h = 0.0
    for _ in range(4):  # itération sur le poids propre de la semelle
        area = nser / q_sol
        # Semelle homothétique au poteau : A/B = a/b
        B = round_up(max(0.60, math.sqrt(area * b / a)))
        A = round_up(max(0.60, area / B))
        d = max((A - a) / 4, (B - b) / 4, 0.15)
        h = round_up(max(0.30, d + cover))
        pp = 25 * A * B * h
        nser, nu = nser_col + pp, nu_col + 1.35 * pp
        if nser / (A * B) <= q_sol + 1e-6:
            break
    d = h - cover
    sigma = nser / (A * B) / 1000
    ok = sigma <= sigma_sol + 1e-6
    if not ok:
        notes.append(f"Contrainte sol {sigma:.3f} MPa > {sigma_sol} MPa")
    # Aciers (m² → cm²) : Ax = Nu (A − a) / (8 d fsu)
    as_x = (nu / 1000) * (A - a) / (8 * d * fsu) * 1e4
    as_y = (nu / 1000) * (B - b) / (8 * d * fsu) * 1e4
    # Espacement 10 à 25 cm → nombre de barres
    def bars_for(as_req: float, width: float) -> Bars | None:
        n_min = max(4, math.ceil((width - 2 * cover) / 0.25) + 1)
        n_max = max(n_min, math.floor((width - 2 * cover) / 0.10) + 1)
        return choose_bars(as_req, n_min=n_min, n_max=n_max, d_min=10, d_max=25)
    return FootingDesign(
        A=A, B=B, h=h, nser=nser, nu=nu, as_x=as_x, as_y=as_y,
        bars_x=bars_for(as_x, B), bars_y=bars_for(as_y, A), ok=ok, notes=notes,
    )
