"""Ossature proposée depuis les murs, toiture légère (charpente) et longrines."""
import pytest

from baticalc.codes import get_code
from baticalc.costing.metre import DevisSettings, compute_metre
from baticalc.design import run
from baticalc.model import LoadSettings
from baticalc.ossature import structure_from_walls

WALLS = [(0, 0, 12, 0), (0, 8, 12, 8), (0, 0, 0, 8), (12, 0, 12, 8), (5, 0, 5.05, 8),   # refend légèrement décalé
         (0, 4.1, 5, 3.95)]


def test_columns_at_corners_junctions_and_spans():
    b = structure_from_walls(WALLS, max_span=4.5)
    xs = sorted({round(c.x, 2) for c in b.columns})
    ys = sorted({round(c.y, 2) for c in b.columns})
    assert xs[0] == 0 and xs[-1] == 12 and any(abs(x - 5.02) < 0.05 for x in xs)
    assert len(ys) == 3                       # 0 ; ≈ 4,0 (murs alignés) ; 8
    cols = b.column_map()
    assert max(bm.length(cols) for bm in b.beams) <= 4.5 + 1e-6
    assert all(bm.direction in ("X", "Y") for bm in b.beams)
    assert b.slab


def test_light_roof_and_longrines():
    b = structure_from_walls(WALLS, max_span=4.5)
    ls = LoadSettings(floor_type="charpente", g_floor=0.40, g_roof_extra=0.0, q_roof=1.0, degression=False,
                      ground_wall_load=7.0)
    res = run(b, ls, get_code("bael"), sigma_sol=0.15)
    assert len(res.longrines) == len(b.beams) and all(r.design.ok for r in res.longrines)
    assert max(r.nser for r in res.columns) < 60          # toiture légère
    no_wall = run(b, LoadSettings(floor_type="charpente", g_floor=0.40, g_roof_extra=0.0, q_roof=1.0,
                                  degression=False), get_code("bael"), sigma_sol=0.15)
    a_with = sum(f.design.A * f.design.B for f in res.footings)
    a_without = sum(f.design.A * f.design.B for f in no_wall.footings)
    assert a_with > a_without                               # maçonnerie reportée sur les semelles
    q = compute_metre(res, DevisSettings(second_oeuvre=False))
    assert "CO-COU" in q and "GO-LON" in q and "GO-DAL" not in q and "GO-HOU" not in q
    assert q["CO-COU"].quantity == pytest.approx(res.takedown.storeys[-1].slab_area * 1.08, rel=1e-6)
