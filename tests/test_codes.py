import math

import pytest

from baticalc.codes import get_code
from baticalc.codes.bael import BAEL
from baticalc.codes.common import bar_area, choose_bars
from baticalc.codes.ec2 import EC2


def test_bael_column_hand_calculation():
    # 30×30, lf = 2,10 m, Nu = 1,5 MN, fc28 = 25, FeE400
    d = BAEL().column(0.30, 0.30, 1500, 2.10)
    lam = 2.10 * math.sqrt(12) / 0.30
    alpha = 0.85 / (1 + 0.2 * (lam / 35) ** 2)
    expected = (1.5 / alpha - 0.28 * 0.28 * 25 / 1.35) * 1.15 / 400 * 1e4
    assert d.slenderness == pytest.approx(lam)
    assert d.as_req == pytest.approx(expected, rel=1e-6)
    assert expected == pytest.approx(13.9, abs=0.1)
    assert d.ok and d.bars.area >= d.as_req
    assert d.bars.n >= 4 and d.bars.n % 2 == 0


def test_bael_column_minimum_steel():
    d = BAEL().column(0.30, 0.30, 200, 2.10)
    assert d.as_req == pytest.approx(4.8)  # 4 cm²/m de périmètre
    assert str(d.bars) == "4HA14"
    assert d.stirrups.d == 6 and d.stirrups.s == pytest.approx(0.21)


def test_bael_column_section_too_small():
    d = BAEL().column(0.20, 0.20, 3000, 2.10)
    assert not d.ok


def test_bael_beam_flexure_hand_calculation():
    code = BAEL()
    as_t, as_c, _ = code.flexure(150, 0.30, 0.50)
    d = 0.45
    mu = 0.150 / (0.30 * d ** 2 * code.fbu)
    alpha = 1.25 * (1 - math.sqrt(1 - 2 * mu))
    expected = 0.150 / (d * (1 - 0.4 * alpha) * 400 / 1.15) * 1e4
    assert as_c == 0
    assert as_t == pytest.approx(expected)
    assert 10 < as_t < 11


def test_bael_mu_limit_fe400():
    mu_l, _ = BAEL()._mu_limit()
    assert mu_l == pytest.approx(0.392, abs=0.002)


def test_ec2_mu_limit_b500():
    mu_l, _ = EC2()._mu_limit()
    assert mu_l == pytest.approx(0.372, abs=0.002)


def test_ec2_compression_steel_when_mu_exceeds_limit():
    as_t, as_c, notes = EC2().flexure(400, 0.25, 0.40)
    assert as_c > 0 and notes


def test_ec2_column_min_steel_and_ok():
    d = EC2().column(0.30, 0.30, 500, 2.10)
    assert d.ok
    assert d.as_req == pytest.approx(max(0.1 * 0.5 / (500 / 1.15), 0.002 * 0.09) * 1e4)


def test_ec2_shear_requires_stirrups():
    d = EC2().beam(0.25, 0.50, 120, 80, 200)
    assert d.ok and d.stirrups.s <= 0.75 * 0.45


def test_choose_bars_practical():
    b = choose_bars(7.5, n_min=2, n_max=8)
    assert b.area >= 7.5
    cands = []
    for d in (10, 12, 14, 16, 20, 25, 32):
        n = max(2, math.ceil(7.5 / bar_area(d)))
        if n <= 8:
            cands.append((n, d, n * bar_area(d)))
    a_min = min(c[2] for c in cands)
    assert b.area <= 1.10 * a_min + 1e-9
    # aucune solution à moins de 10 % de l'optimum n'a moins de barres
    assert all(n >= b.n for n, d, a in cands if a <= 1.10 * a_min + 1e-9)
    # 11 cm² : 14HA10 (11,0) est écarté au profit d'une solution à moins de barres
    assert choose_bars(11.0, n_min=2, n_max=16).n < 14


def test_cm66_not_yet_available():
    with pytest.raises(NotImplementedError):
        get_code("cm66")
