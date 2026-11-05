"""Escaliers : géométrie (Blondel), paillasse + palier, intégration au calcul."""
import math

import ezdxf
import pytest

from koordinia.codes import get_code
from koordinia.design import run
from koordinia.importers import import_plan
from koordinia.model import LoadSettings
from koordinia.recognition import build_model
from koordinia.stairs import design_stair


def test_geometry_blondel():
    st = design_stair(get_code("bael"), "N1 → N2", "Escalier", 5.2, 4.4, 3.40)
    assert st.risers == 20 and st.riser_h == pytest.approx(0.17)
    assert 0.60 <= 2 * st.riser_h + st.going <= 0.66
    assert st.flights == 2 and st.width == pytest.approx(2.2)
    assert st.flight_len == pytest.approx(9 * st.going, abs=0.01)
    assert st.thickness >= st.span / 30
    assert not st.notes


def test_single_flight_and_short_cage():
    st = design_stair(get_code("ec2"), "N1 → N2", "Escalier", 3.0, 1.2, 3.0)
    assert st.flights == 1
    assert any("trop courte" in n for n in st.notes)


def test_moment_uniform_case():
    """Volée seule sans palier : M0 = pu·L²/8 avec pu de la volée."""
    code = get_code("bael")
    st = design_stair(code, "x", "Escalier", 10 * 0.29 + 0.0 + 0.0, 1.0, 1.70)  # 10 marches
    # palier nul → charge uniforme de volée
    if st.landing < 0.01:
        pu = code.elu(st.g_flight, 2.5)
        assert st.m0 == pytest.approx(pu * st.span ** 2 / 8, rel=0.01)
    assert st.angle == pytest.approx(math.degrees(math.atan(st.riser_h / st.going)), abs=0.1)


def test_stair_in_project(tmp_path):
    from test_zones import write_rooms_dxf

    path = write_rooms_dxf(tmp_path / "l.dxf")
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    k = 100.0
    # cage d'escalier 2,6 × 4,4 m (murs) avec ses marches, dans le bureau
    msp.add_lwpolyline([(0.2 * k, 3.4 * k), (2.8 * k, 3.4 * k), (2.8 * k, 7.8 * k), (0.2 * k, 7.8 * k)], close=True,
                       dxfattribs={"layer": "A-MURS"})
    for i in range(12):
        y = (3.7 + i * 0.29) * k
        msp.add_line((0.2 * k, y), (1.4 * k, y), dxfattribs={"layer": "ESCALIER"})
    msp.add_mtext("Escalier 11.44m²", dxfattribs={"layer": "AR_TEXTES", "insert": (1.5 * k, 5.5 * k),
                                                  "char_height": 15})
    doc.saveas(path)
    bld = build_model(import_plan(path), n_levels=3, floor_height=3.06)
    assert any(z["type"] == "escalier" for z in bld.zones)
    res = run(bld, LoadSettings(), get_code("bael"))
    assert len(res.stairs) == 1
    st = res.stairs[0]
    assert st.height == pytest.approx(3.06)
    assert st.risers == 18
    assert st.bars_bottom.startswith("HA")
    assert st.landing_beam_load > 0
