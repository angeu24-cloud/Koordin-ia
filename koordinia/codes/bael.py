"""BAEL 91 révisé 99 — béton armé, fissuration peu préjudiciable, durée > 24 h (θ = 1)."""
from __future__ import annotations

import math

from .common import (
    BeamDesign, ColumnDesign, FootingDesign, Stirrups, choose_bars, footing_design, stirrup_spacing,
)

ES = 200_000.0  # MPa


class BAEL:
    name = "BAEL 91 mod. 99"
    short = "bael"
    gamma_b = 1.5
    gamma_s = 1.15

    def __init__(self, fc28: float = 25.0, fe: float = 400.0, cover: float = 0.03):
        self.fc28, self.fe, self.cover = fc28, fe, cover
        self.ft28 = 0.6 + 0.06 * fc28
        self.fbu = 0.85 * fc28 / self.gamma_b
        self.sigma_s = fe / self.gamma_s

    def describe(self) -> list[str]:
        return [
            f"Béton : fc28 = {self.fc28:g} MPa ; ft28 = {self.ft28:.2f} MPa ; fbu = {self.fbu:.2f} MPa (γb = 1,5)",
            f"Acier : FeE{self.fe:g} ; σs = fe/γs = {self.sigma_s:.0f} MPa (γs = 1,15)",
            "Combinaisons : ELU = 1,35 G + 1,5 Q ; ELS = G + Q",
            "Fissuration peu préjudiciable ; enrobage "
            f"{self.cover * 100:.0f} cm",
        ]

    @staticmethod
    def elu(g: float, q: float) -> float:
        return 1.35 * g + 1.5 * q

    @staticmethod
    def els(g: float, q: float) -> float:
        return g + q

    # ------------------------------------------------------------------ poteaux
    def column(self, b: float, h: float, nu_kn: float, lf: float) -> ColumnDesign:
        notes: list[str] = []
        a = min(b, h)
        lam = lf * math.sqrt(12) / a
        if lam <= 50:
            alpha = 0.85 / (1 + 0.2 * (lam / 35) ** 2)
        elif lam <= 70:
            alpha = 0.6 * (50 / lam) ** 2
        else:
            alpha = 0.0
            notes.append(f"Élancement λ = {lam:.1f} > 70 : hors domaine de la méthode forfaitaire")
        br = (b - 0.02) * (h - 0.02)
        nu = nu_kn / 1000  # MN
        as_min = max(4.0 * 2 * (b + h), 0.2 / 100 * b * h * 1e4)  # cm²
        as_max = 5.0 / 100 * b * h * 1e4
        if alpha > 0:
            as_th = (nu / alpha - br * self.fc28 / (0.9 * self.gamma_b)) * self.gamma_s / self.fe * 1e4
        else:
            as_th = float("inf")
        as_req = max(as_th, as_min)
        ok = as_req <= as_max
        if not ok:
            notes.append("Section de béton insuffisante (A > 5 % B)")
        bars = None
        if ok:
            # Au moins une barre par angle ; espacement des barres ≤ min(a + 10 cm ; 40 cm)
            c_max = min(a + 0.10, 0.40)
            per_x = max(2, math.ceil((b - 2 * self.cover) / c_max) + 1)
            per_y = max(2, math.ceil((h - 2 * self.cover) / c_max) + 1)
            n_min = 2 * per_x + 2 * per_y - 4
            bars = choose_bars(as_req, n_min=n_min, n_max=max(n_min, 20), d_min=12, d_max=32, even=True)
        stirrups = None
        if bars:
            dt = next(x for x in (6, 8, 10, 12) if x >= bars.d / 3)  # φt ≥ φl/3
            st = min(15 * bars.d / 1000, 0.40, a + 0.10)
            stirrups = Stirrups(dt, math.floor(st * 100) / 100)
        return ColumnDesign(b, h, nu_kn, as_req, as_min, as_max, bars, stirrups, lam, ok and bars is not None, notes)

    # ------------------------------------------------------------------ poutres
    def _mu_limit(self) -> tuple[float, float]:
        eps_l = self.fe / (self.gamma_s * ES)
        alpha_l = 3.5 / (3.5 + 1000 * eps_l)
        return 0.8 * alpha_l * (1 - 0.4 * alpha_l), alpha_l

    def flexure(self, mu_knm: float, b: float, h: float) -> tuple[float, float, list[str]]:
        """Renvoie (As tendus, As comprimés) en cm² pour une section rectangulaire."""
        notes: list[str] = []
        d = 0.9 * h
        dp = self.cover + 0.01
        mu_m = abs(mu_knm) / 1000
        mu = mu_m / (b * d ** 2 * self.fbu)
        mu_l, alpha_l = self._mu_limit()
        as_min = 0.23 * b * d * self.ft28 / self.fe * 1e4
        if mu <= mu_l:
            alpha = 1.25 * (1 - math.sqrt(1 - 2 * mu))
            z = d * (1 - 0.4 * alpha)
            return max(mu_m / (z * self.sigma_s) * 1e4, as_min), 0.0, notes
        notes.append(f"μ = {mu:.3f} > μl = {mu_l:.3f} : aciers comprimés nécessaires (augmenter h conseillé)")
        mr = mu_l * b * d ** 2 * self.fbu
        zl = d * (1 - 0.4 * alpha_l)
        a_comp = (mu_m - mr) / ((d - dp) * self.sigma_s)
        a_t = mr / (zl * self.sigma_s) + a_comp
        return max(a_t * 1e4, as_min), a_comp * 1e4, notes

    def beam(self, b: float, h: float, mu_span: float, mu_support: float, vu: float) -> BeamDesign:
        notes: list[str] = []
        as_span, a_comp1, n1 = self.flexure(mu_span, b, h)
        as_sup, a_comp2, n2 = self.flexure(mu_support, b, h)
        notes += n1 + n2
        d = 0.9 * h
        tau = vu / 1000 / (b * d)
        tau_lim = min(0.2 * self.fc28 / self.gamma_b, 5.0)
        ok = tau <= tau_lim
        if not ok:
            notes.append(f"τu = {tau:.2f} MPa > τlim = {tau_lim:.2f} MPa : augmenter la section")
        at_st = max((tau - 0.3 * self.ft28) * b * self.gamma_s / (0.9 * self.fe), 0.4 * b / self.fe) * 1e4  # cm²/m
        s_max = min(0.9 * d, 0.40)
        dt = 6 if h <= 0.45 else 8
        stirrups = Stirrups(dt, stirrup_spacing(at_st, dt, 2, s_max))
        n_layer = max(2, math.floor((b - 2 * self.cover - 0.016) / 0.045) + 1)
        bottom = choose_bars(as_span, n_min=2, n_max=2 * n_layer, d_min=10)
        top = choose_bars(max(as_sup, a_comp1), n_min=2, n_max=2 * n_layer, d_min=10)
        if bottom is None or top is None:
            ok = False
            notes.append("Armatures impossibles à loger : augmenter la section")
        return BeamDesign(b, h, mu_span, mu_support, vu, as_span, as_sup, max(a_comp1, a_comp2),
                          bottom, top, stirrups, ok, notes)

    # --------------------------------------------------------------- fondations
    def footing(self, a: float, b: float, nser: float, nu: float, sigma_sol: float) -> FootingDesign:
        return footing_design(a, b, nser, nu, sigma_sol, self.sigma_s)
