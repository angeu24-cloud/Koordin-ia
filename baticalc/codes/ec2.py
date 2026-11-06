"""Eurocode 2 (NF EN 1992-1-1 + Annexe Nationale française) — béton armé, bâtiments courants."""
from __future__ import annotations

import math

from .common import (
    BeamDesign, ColumnDesign, FootingDesign, Stirrups, choose_bars, footing_design, stirrup_spacing,
)

ES = 200_000.0


class EC2:
    name = "Eurocode 2 (NF EN 1992-1-1/NA)"
    short = "ec2"
    gamma_c = 1.5
    gamma_s = 1.15

    def __init__(self, fck: float = 25.0, fyk: float = 500.0, cover: float = 0.03):
        self.fck, self.fyk, self.cover = fck, fyk, cover
        self.fcd = fck / self.gamma_c          # αcc = 1 (AN France)
        self.fyd = fyk / self.gamma_s
        self.fctm = 0.30 * fck ** (2 / 3)

    def describe(self) -> list[str]:
        return [
            f"Béton C{self.fck:g} : fcd = {self.fcd:.2f} MPa (αcc = 1, γc = 1,5) ; fctm = {self.fctm:.2f} MPa",
            f"Acier B{self.fyk:g} : fyd = {self.fyd:.0f} MPa (γs = 1,15)",
            "Combinaisons (EN 1990, 6.10) : ELU = 1,35 G + 1,5 Q ; ELS caractéristique = G + Q",
            f"Classe d'exposition XC1 supposée ; enrobage {self.cover * 100:.0f} cm",
        ]

    @staticmethod
    def elu(g: float, q: float) -> float:
        return 1.35 * g + 1.5 * q

    @staticmethod
    def els(g: float, q: float) -> float:
        return g + q

    # ------------------------------------------------------------------ poteaux
    def column(self, b: float, h: float, ned_kn: float, lf: float) -> ColumnDesign:
        """Méthode simplifiée des Recommandations professionnelles (poteaux rectangulaires,
        compression centrée) : N_Rd = kh·ks·α·(Ac·fcd + As·fyd)."""
        notes: list[str] = []
        a = min(b, h)
        lam = lf * math.sqrt(12) / a
        if lam <= 60:
            alpha = 0.86 / (1 + (lam / 62) ** 2)
        elif lam <= 120:
            alpha = (32 / lam) ** 1.3
        else:
            alpha = 0.0
            notes.append(f"Élancement λ = {lam:.1f} > 120 : hors domaine de la méthode simplifiée")
        ks = 1.0 if (self.fyk <= 500 or lam <= 40) else 1.6 - 0.6 * self.fyk / 500
        ac = b * h
        ned = ned_kn / 1000
        delta = (self.cover + 0.01) / a
        as_th = float("inf")
        if alpha > 0:
            rho = 0.01
            for _ in range(20):
                kh = 1.0 if a >= 0.50 else (0.75 + 0.5 * a) * (1 - 6 * rho * delta)
                as_m2 = (ned / (kh * ks * alpha) - ac * self.fcd) / self.fyd
                new_rho = max(as_m2, 0) / ac
                if abs(new_rho - rho) < 1e-6:
                    break
                rho = new_rho
            as_th = as_m2 * 1e4
        as_min = max(0.10 * ned / self.fyd, 0.002 * ac) * 1e4
        as_max = 0.04 * ac * 1e4
        as_req = max(as_th, as_min)
        ok = as_req <= as_max
        if not ok:
            notes.append("Section de béton insuffisante (As > 4 % Ac)")
        bars = None
        if ok:
            c_max = 0.40
            per_x = max(2, math.ceil((b - 2 * self.cover) / c_max) + 1)
            per_y = max(2, math.ceil((h - 2 * self.cover) / c_max) + 1)
            n_min = 2 * per_x + 2 * per_y - 4
            bars = choose_bars(as_req, n_min=n_min, n_max=max(n_min, 20), d_min=12, d_max=32, even=True)
        stirrups = None
        if bars:
            dt = next(x for x in (6, 8, 10) if x >= bars.d / 4)  # φt ≥ max(6 ; φl/4)
            s = min(20 * bars.d / 1000, a, 0.40)
            stirrups = Stirrups(dt, math.floor(s * 100) / 100)
        return ColumnDesign(b, h, ned_kn, as_req, as_min, as_max, bars, stirrups, lam, ok and bars is not None, notes)

    # ------------------------------------------------------------------ poutres
    def _mu_limit(self) -> tuple[float, float]:
        eps_yd = self.fyd / ES
        alpha_l = 3.5 / (3.5 + 1000 * eps_yd)
        return 0.8 * alpha_l * (1 - 0.4 * alpha_l), alpha_l

    def flexure(self, med_knm: float, b: float, h: float) -> tuple[float, float, list[str]]:
        notes: list[str] = []
        d = 0.9 * h
        dp = self.cover + 0.01
        m = abs(med_knm) / 1000
        mu = m / (b * d ** 2 * self.fcd)
        mu_l, alpha_l = self._mu_limit()
        as_min = max(0.26 * self.fctm / self.fyk, 0.0013) * b * d * 1e4
        if mu <= mu_l:
            alpha = 1.25 * (1 - math.sqrt(1 - 2 * mu))
            z = d * (1 - 0.4 * alpha)
            return max(m / (z * self.fyd) * 1e4, as_min), 0.0, notes
        notes.append(f"μ = {mu:.3f} > μlu = {mu_l:.3f} : aciers comprimés nécessaires (augmenter h conseillé)")
        mr = mu_l * b * d ** 2 * self.fcd
        zl = d * (1 - 0.4 * alpha_l)
        a_comp = (m - mr) / ((d - dp) * self.fyd)
        return max((mr / (zl * self.fyd) + a_comp) * 1e4, as_min), a_comp * 1e4, notes

    def beam(self, b: float, h: float, mu_span: float, mu_support: float, ved: float) -> BeamDesign:
        notes: list[str] = []
        as_span, a_comp1, n1 = self.flexure(mu_span, b, h)
        as_sup, a_comp2, n2 = self.flexure(mu_support, b, h)
        notes += n1 + n2
        d = 0.9 * h
        z = 0.9 * d
        v = ved / 1000
        # Résistance sans armatures d'effort tranchant (6.2.2)
        k = min(2.0, 1 + math.sqrt(0.2 / d))
        rho_l = min(0.02, as_span / 1e4 / (b * d))
        v_rdc = max(0.18 / self.gamma_c * k * (100 * rho_l * self.fck) ** (1 / 3),
                    0.035 * k ** 1.5 * self.fck ** 0.5) * b * d
        # Bielles à 45° (cotθ = 1), sécuritaire
        nu1 = 0.6 * (1 - self.fck / 250)
        v_rdmax = b * z * nu1 * self.fcd / 2
        ok = v <= v_rdmax
        if not ok:
            notes.append(f"VEd = {ved:.0f} kN > VRd,max = {v_rdmax * 1000:.0f} kN : augmenter la section")
        rho_w_min = 0.08 * math.sqrt(self.fck) / self.fyk
        asw_s = max(v / (z * self.fyd) if v > v_rdc else 0.0, rho_w_min * b) * 1e4  # cm²/m
        s_max = min(0.75 * d, 0.60)
        dt = 6 if h <= 0.45 else 8
        stirrups = Stirrups(dt, stirrup_spacing(asw_s, dt, 2, s_max))
        n_layer = max(2, math.floor((b - 2 * self.cover - 0.016) / 0.045) + 1)
        bottom = choose_bars(as_span, n_min=2, n_max=2 * n_layer, d_min=10)
        top = choose_bars(max(as_sup, a_comp1), n_min=2, n_max=2 * n_layer, d_min=10)
        if bottom is None or top is None:
            ok = False
            notes.append("Armatures impossibles à loger : augmenter la section")
        return BeamDesign(b, h, mu_span, mu_support, ved, as_span, as_sup, max(a_comp1, a_comp2),
                          bottom, top, stirrups, ok, notes)

    # --------------------------------------------------------------- fondations
    def footing(self, a: float, b: float, nser: float, nu: float, sigma_sol: float,
                depth: float | None = None) -> FootingDesign:
        return footing_design(a, b, nser, nu, sigma_sol, self.fyd, depth=depth)
