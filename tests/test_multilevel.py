"""Projet multi-niveaux : niveaux lus sur la coupe, planche par niveau, calage,
poteau naissant (poutre de transfert), poteau sur mur, équilibre global."""
import ezdxf
import pytest

from baticalc.cli import main
from baticalc.codes import get_code
from baticalc.design import run
from baticalc.importers import import_plan
from baticalc.levels import canonical_level, read_elevations, sheet_levels
from baticalc.model import LoadSettings
from baticalc.project import Project, build_project
from baticalc.sheets import find_sheets
from baticalc.takedown import CONCRETE, compute_takedown

CM = 100.0


def _poly(msp, pts, layer, close=True):
    msp.add_lwpolyline([(x * CM, y * CM) for x, y in pts], close=close, dxfattribs={"layer": layer})


def _rect(msp, x0, y0, x1, y1, layer, hatch=False):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    _poly(msp, pts, layer)
    if hatch:
        h = msp.add_hatch(dxfattribs={"layer": layer})
        h.paths.add_polyline_path([(x * CM, y * CM) for x, y in pts], is_closed=True)


def _sheet(msp, ox, title):
    _rect(msp, ox, 0, ox + 60, 40, "0")
    _rect(msp, ox + 40, 0.3, ox + 59.7, 8, "0")
    msp.add_mtext(title, dxfattribs={"layer": "AR_TEXTES", "insert": ((ox + 45) * CM, 6 * CM), "char_height": 30})


def _building(msp, bx, by, cols, extra_walls=()):
    for off in (0.0, 0.2):  # murs de façade 8 × 8 m (double trait)
        _rect(msp, bx - 0.2 + off, by - 0.2 + off, bx + 8.2 - off, by + 8.2 - off, "A-MURS")
    for x, y in cols:
        _rect(msp, bx + x - 0.125, by + y - 0.125, bx + x + 0.125, by + y + 0.125, "POTEAUX", hatch=True)
    for x0, y0, x1, y1 in extra_walls:
        _rect(msp, bx + x0, by + y0, bx + x1, by + y1, "A-MURS")


GRID = [(x, y) for y in (0, 4, 8) for x in (0, 4, 8)]


def write_project_dxf(path, rdc_offset=(0.37, -0.21)):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5
    for n in ("A-MURS", "POTEAUX", "AR_TEXTES"):
        doc.layers.add(n)
    msp = doc.modelspace()
    _rect(msp, -5, -5, 200, 50, "0")  # cadre général
    _sheet(msp, 0, "VUE EN PLAN RDC")
    _sheet(msp, 65, "VUE EN PLAN ETAGE COURANT")
    _sheet(msp, 130, "COUPE A-A")
    # Étage courant : trame complète 3 × 3
    _building(msp, 75, 15, GRID)
    # RDC (décalé dans sa planche) : sans le poteau central (4,4) → porté par la poutre (0,4)-(8,4) ;
    # sans le poteau d'angle (8,8)… remplacé par un mur porteur intérieur le long de y = 6,5 → non ;
    # on retire (4,8) qui repose sur le mur de façade nord.
    rdc_cols = [c for c in GRID if c not in ((4, 4), (4, 8))]
    _building(msp, 10 + rdc_offset[0], 15 + rdc_offset[1], rdc_cols)
    # Coupe : étiquettes de niveaux alignées
    z = 10.0
    for name, h in (("RDC", 3.20), ("Etage 1", 3.00), ("Etage 2", 3.00), ("Terrasse", 0)):
        msp.add_mtext(name, dxfattribs={"layer": "A-FLOR-LEVL", "insert": (150 * CM, z * CM), "char_height": 20})
        z += h
    doc.saveas(path)
    return path


@pytest.fixture
def proj_dxf(tmp_path):
    return write_project_dxf(tmp_path / "projet.dxf")


def test_level_names():
    assert canonical_level("Etage 1") == "ETAGE 1"
    assert canonical_level("R.D.C") == "RDC"
    assert canonical_level("Rez-de-jardin") == "RDJ"
    assert canonical_level("2ème étage") == "ETAGE 2"
    assert canonical_level("Bureaux") is None
    assert sheet_levels("VUE EN PLAN ETAGE COURANT 1 ET 3") == (["ETAGE 1", "ETAGE 3"], True)
    assert sheet_levels("PLAN ETAGES 1 A 3")[0] == ["ETAGE 1", "ETAGE 2", "ETAGE 3"]


def test_elevations_from_section(proj_dxf):
    d = import_plan(proj_dxf)
    levels, _ = read_elevations(d, find_sheets(d))
    assert [(lv.name, lv.elevation) for lv in levels] == [
        ("RDC", 0.0), ("ETAGE 1", 3.2), ("ETAGE 2", 6.2), ("TERRASSE", 9.2)]


def test_build_project(proj_dxf):
    proj = build_project(import_plan(proj_dxf))
    assert [(s.name, s.height) for s in proj.storeys] == [("RDC", 3.2), ("Étage 1", 3.0), ("Étage 2", 3.0)]
    assert [len(s.plan.columns) for s in proj.storeys] == [7, 9, 9]
    # calage : les poteaux superposés ont les mêmes coordonnées et le même repère
    rdc, e1 = proj.storeys[0].plan.column_map(), proj.storeys[1].plan.column_map()
    common = set(rdc) & set(e1)
    assert len(common) == 7
    for cid in common:
        assert rdc[cid].x == pytest.approx(e1[cid].x, abs=0.02)
        assert rdc[cid].y == pytest.approx(e1[cid].y, abs=0.02)
    # sauvegarde / relecture
    proj2 = Project.from_dict(proj.to_dict())
    assert [len(s.plan.beams) for s in proj2.storeys] == [len(s.plan.beams) for s in proj.storeys]


def test_transfer_and_wall_support(proj_dxf):
    proj = build_project(import_plan(proj_dxf))
    ls = LoadSettings(continuity=False, degression=False)
    td = compute_takedown(proj, ls)
    e1 = proj.storeys[1].plan
    centre = next(c.id for c in e1.columns if (c.x, c.y) == pytest.approx((4, 4), abs=0.05))
    nord = next(c.id for c in e1.columns if (c.x, c.y) == pytest.approx((4, 8), abs=0.05))
    # poteau central naissant : porté par une poutre du plancher haut RDC
    pl = td.storeys[0].point_loads
    assert any(p[3] == centre for loads in pl.values() for p in loads)
    # poteau nord : repose sur le mur de façade du RDC
    assert [w.column_id for w in td.wall_supports] == [nord]

    # Équilibre global : charges appliquées = pieds des poteaux du RDC + charges sur murs
    g_applied = q_applied = 0.0
    for k, st in enumerate(proj.storeys):
        roof = k == proj.n - 1
        sl = td.storeys[k]
        g_applied += sl.slab_area * (td.surface_g_roof if roof else td.surface_g_floor)
        q_applied += sl.slab_area * (td.surface_q_roof if roof else td.surface_q_floor)
        cols = st.plan.column_map()
        g_applied += sum(CONCRETE * b.b * b.h * b.length(cols) for b in st.plan.beams)
        g_applied += sum(CONCRETE * c.b * c.h * st.height for c in st.plan.columns)
    base = [s for v in td.columns.values() for s in v if s.storey == 1]
    g_out = sum(s.g for s in base) + sum(w.g for w in td.wall_supports)
    q_out = sum(s.q for s in base) + sum(w.q for w in td.wall_supports)
    assert g_out == pytest.approx(g_applied, rel=1e-6)
    assert q_out == pytest.approx(q_applied, rel=1e-6)


def test_single_plan_project_matches_building(tmp_path):
    """Un projet fait du même plan répété donne la même descente que le mode plan unique."""
    from baticalc.recognition import build_model
    from baticalc.sample import write_sample_dxf

    bld = build_model(import_plan(write_sample_dxf(tmp_path / "p.dxf")), n_levels=4, floor_height=3.0)
    ls = LoadSettings()
    td1 = compute_takedown(bld, ls)
    proj = Project([__import__("baticalc.project", fromlist=["Storey"]).Storey(f"N{k}", 3.0, bld)
                    for k in range(4)])
    td2 = compute_takedown(proj, ls)
    for cid, stacks in td1.columns.items():
        for a, b in zip(stacks, td2.columns[cid]):
            assert a.g == pytest.approx(b.g) and a.q == pytest.approx(b.q)


def test_degression_multilevel(proj_dxf):
    proj = build_project(import_plan(proj_dxf))
    td_d = compute_takedown(proj, LoadSettings(degression=True))
    td_n = compute_takedown(proj, LoadSettings(degression=False))
    # 3 planchers : terrasse + 2 → m = 2 au RDC, coefficient 0,95 sur les 2 planchers courants
    checked = 0
    for cid, st in td_d.columns.items():
        base_d = next((s for s in st if s.storey == 1), None)
        if base_d is None:  # poteau naissant à l'étage
            continue
        base_n = next(s for s in td_n.columns[cid] if s.storey == 1)
        assert base_d.q <= base_n.q + 1e-9
        checked += 1
    assert checked == 7


def test_cli_multilevel(proj_dxf, tmp_path):
    out = tmp_path / "res"
    assert main(["niveaux", str(proj_dxf)]) == 0
    assert main(["calculer", str(proj_dxf), "--tous-niveaux", "--norme", "bael", "-o", str(out)]) == 0
    for name in ("projet.json", "coffrage_01_plancher_haut_rdc.dxf", "coffrage_03_terrasse.dxf",
                 "plan_fondations.dxf", "plans_ferraillage.dxf", "note_de_calcul.pdf"):
        assert (out / name).exists(), name
    assert main(["calculer", "--modele", str(out / "projet.json"), "--norme", "ec2", "-o", str(out / "ec2")]) == 0
    res = run(Project.load(out / "projet.json"), LoadSettings(), get_code("bael"))
    assert any(r.transfer for r in res.beams)
    assert any(f.on_wall for f in res.footings)


def test_automatic_transfer_beam(proj_dxf):
    """Sans poutre sous le poteau central (portées > 7 m non créées), une poutre de transfert
    est créée entre les deux poteaux alignés les plus proches ; l'équilibre est conservé."""
    proj = build_project(import_plan(proj_dxf), max_span=7.0)
    ls = LoadSettings(continuity=False, degression=False)
    td = compute_takedown(proj, ls)
    assert len(td.transfers) == 1
    tb = td.transfers[0]
    e1 = proj.storeys[1].plan
    centre = next(c.id for c in e1.columns if (c.x, c.y) == pytest.approx((4, 4), abs=0.05))
    assert [l[3] for l in tb.loads] == [centre]
    assert tb.length == pytest.approx(8.0, abs=0.05)
    assert all(sp[0] == "poteau" for sp in tb.supports)
    assert tb.loads[0][0] == pytest.approx(4.0, abs=0.05)   # à mi-portée

    g_applied = q_applied = 0.0
    for k, st in enumerate(proj.storeys):
        roof = k == proj.n - 1
        sl = td.storeys[k]
        g_applied += sl.slab_area * (td.surface_g_roof if roof else td.surface_g_floor)
        q_applied += sl.slab_area * (td.surface_q_roof if roof else td.surface_q_floor)
        cols = st.plan.column_map()
        g_applied += sum(CONCRETE * b.b * b.h * b.length(cols) for b in st.plan.beams)
        g_applied += sum(CONCRETE * c.b * c.h * st.height for c in st.plan.columns)
    g_applied += CONCRETE * tb.b * tb.h * tb.length
    base = [s for v in td.columns.values() for s in v if s.storey == 1]
    g_out = sum(s.g for s in base) + sum(w.g for w in td.wall_supports)
    q_out = sum(s.q for s in base) + sum(w.q for w in td.wall_supports)
    assert g_out == pytest.approx(g_applied, rel=1e-6)
    assert q_out == pytest.approx(q_applied, rel=1e-6)

    res = run(proj, LoadSettings(), get_code("bael"))
    assert len(res.transfers) == 1 and res.transfers[0].design.ok
    assert res.transfers[0].design.h >= 0.80   # portée 8 m, poteau de 2 niveaux
