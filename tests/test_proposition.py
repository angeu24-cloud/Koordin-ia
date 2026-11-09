"""Ossature proposée d'après les murs (plans d'architecte sans poteaux) : murs porteurs, poutres de
rive, recoupement des grands planchers, continuité verticale d'un duplex."""
import math

import ezdxf
import numpy as np

from baticalc.codes import get_code
from baticalc.design import run
from baticalc.importers import import_plan
from baticalc.model import LoadSettings
from baticalc.ossature import structure_from_walls, structure_on_slab
from baticalc.project import build_project
from baticalc.recognition import structural_walls
from baticalc.slab import SlabMask

CM = 100.0


def _rect(msp, x0, y0, x1, y1, layer="A-MURS"):
    msp.add_lwpolyline([(x * CM, y * CM) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))], close=True,
                       dxfattribs={"layer": layer})


def _house(msp, bx, by, w, h, walls):
    for off in (0.0, 0.2):    # façades de 20 cm (double trait)
        _rect(msp, bx - 0.1 + off, by - 0.1 + off, bx + w + 0.1 - off, by + h + 0.1 - off)
    for x0, y0, x1, y1 in walls:
        _rect(msp, bx + x0, by + y0, bx + x1, by + y1)


def V(x, y0, y1):
    return (x - 0.1, y0, x + 0.1, y1)


def H(y, x0, x1):
    return (x0, y - 0.1, x1, y + 0.1)


def write_duplex(path):
    """RDC 12 × 9 m : séjour ouvert 6 × 9 à gauche, chambres à droite ; étage : refend y = 4,5 sur toute
    la longueur et cloison x = 3 au-dessus du séjour. Aucun poteau dessiné."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5
    msp = doc.modelspace()
    _rect(msp, -5, -5, 200, 50, "0")
    for ox, title in ((0, "VUE EN PLAN RDC"), (65, "VUE EN PLAN ETAGE 1"), (130, "COUPE A-A")):
        _rect(msp, ox, 0, ox + 60, 40, "0")
        _rect(msp, ox + 40, 0.3, ox + 59.7, 8, "0")
        msp.add_mtext(title, dxfattribs={"layer": "AR_TEXTES", "insert": ((ox + 45) * CM, 6 * CM), "char_height": 30})
    _house(msp, 10.37, 15.21, 12, 9, [V(6, 0.1, 8.9), H(4.5, 6.1, 11.9), V(9, 4.6, 8.9)])
    _house(msp, 75, 15, 12, 9, [V(6, 0.1, 8.9), H(4.5, 0.1, 11.9), V(3, 4.6, 8.9), V(9, 4.6, 8.9)])
    z = 10.0
    for name, h in (("RDC", 3.0), ("Etage 1", 3.0), ("Terrasse", 0)):
        msp.add_mtext(name, dxfattribs={"layer": "A-FLOR-LEVL", "insert": (150 * CM, z * CM), "char_height": 20})
        z += h
    doc.saveas(path)
    return path


def test_structural_walls_join_openings_and_drop_partitions():
    walls = [[0, 0, 2.0, 0, 0.2], [2.9, 0, 6, 0, 0.2],      # façade coupée par une porte de 0,9 m
             [0, 0, 0, 4, 0.2], [6, 0, 6, 4, 0.2], [0, 4, 6, 4, 0.2],
             [3, 0, 3, 4, 0.07]]                              # cloison de 7 cm : non porteuse
    out, gaps = structural_walls(walls, None)
    assert [0, 0, 6, 0, 0.2] in out
    assert not any(abs(w[0] - 3) < 0.01 and abs(w[2] - 3) < 0.01 for w in out)
    assert gaps == [(2.0, 0, 2.9, 0)]


def test_columns_avoid_openings_and_virtual_beams():
    walls = [(0, 0, 9, 0), (0, 6, 9, 6), (0, 0, 0, 6), (9, 0, 9, 6)]
    b = structure_from_walls(walls, max_span=4.5, avoid=[(4.2, 0, 5.2, 0)])
    xs = sorted(c.x for c in b.columns if abs(c.y) < 0.01)
    assert all(not (4.05 < x < 5.35) for x in xs)          # pas de poteau dans la baie
    # poutre virtuelle de 6 m au milieu : poteaux à ses extrémités sur les façades, aucun au milieu
    b2 = structure_from_walls(walls + [(4.5, 0, 4.5, 6, "v")], max_span=4.5)
    assert not any(abs(c.x - 4.5) < 0.01 and 0.5 < c.y < 5.5 for c in b2.columns)
    assert any(abs(c.x - 4.5) < 0.01 and abs(c.y) < 0.01 for c in b2.columns)


def test_open_floor_is_recut():
    """Plateau de 16 × 12 m sans mur intérieur : files ajoutées jusqu'à des portées de dalle ≤ 5,5 m."""
    m = np.zeros((140, 180), dtype=bool)
    m[10:130, 10:170] = True
    mask = SlabMask(0.10, -1.0, -1.0, m)
    walls = [(0, 0, 16, 0), (0, 11.9, 16, 11.9), (0, 0, 0, 11.9), (15.9, 0, 15.9, 11.9)]
    b = structure_on_slab(walls, mask, max_span=4.5, slab_span=5.5)
    from baticalc.ossature import unsupported

    assert unsupported(b, mask, slab_span=5.5).sum() * 0.01 < 1.0
    assert len(b.walls) == 4 and any("file(s) de poutres" in w for w in b.warnings)


def test_duplex_without_columns(tmp_path):
    proj = build_project(import_plan(write_duplex(tmp_path / "duplex.dxf")))
    rdc, et = proj.storeys
    assert rdc.plan.proposed and et.plan.proposed
    for st in proj.storeys:           # angles de la maison
        for x, y in ((0, 0), (12, 0), (0, 9), (12, 9)):
            assert any(math.hypot(c.x - x, c.y - y) < 0.05 for c in st.plan.columns), (st.name, x, y)
        assert len({c.id for c in st.plan.columns}) == len(st.plan.columns)
    # séjour du RDC (0 < x < 6, 0 < y < 9) : aucun poteau à l'intérieur
    assert not any(0.5 < c.x < 5.5 and 0.5 < c.y < 8.5 for c in rdc.plan.columns)
    # poteau d'étage sur la cloison x = 3 : naissant, porté par une poutre du RDC sous le refend y = 4,5
    assert any(abs(c.x - 3) < 0.05 and abs(c.y - 4.5) < 0.05 for c in et.plan.columns)
    assert any("naissant" in w for w in proj.warnings)
    cm = rdc.plan.column_map()
    assert any(abs(cm[b.start].y - 4.5) < 0.05 and abs(cm[b.end].y - 4.5) < 0.05
               and min(cm[b.start].x, cm[b.end].x) < 0.05 and max(cm[b.start].x, cm[b.end].x) > 5.95
               for b in rdc.plan.beams)
    # les poteaux superposés portent le même repère
    ids = {(round(c.x, 2), round(c.y, 2)): c.id for c in rdc.plan.columns}
    for c in et.plan.columns:
        if (round(c.x, 2), round(c.y, 2)) in ids:
            assert ids[(round(c.x, 2), round(c.y, 2))] == c.id
    res = run(proj, LoadSettings(), get_code("bael"), sigma_sol=0.15)
    assert len(res.footings) == len(rdc.plan.columns) and res.beams and res.columns


def test_revit_level_labels_and_written_elevations():
    from baticalc.levels import canonical_level, level_elevation, sheet_levels

    assert canonical_level("±0,000\n0 Rez-de-chaussée") == "RDC"
    assert canonical_level("+3,200\n1 Étage") == "ETAGE 1"
    assert level_elevation("+3,200\n1 Étage") == 3.2 and level_elevation("RDC") is None
    assert sheet_levels("PLAN COTE ETAGE") == ([], True)       # étage sans numéro : étage courant


def test_sheets_without_frames_named_by_titles(tmp_path):
    from baticalc.sheets import find_sheets

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for ox, title in ((0, "PLAN COTE RDC"), (30, "PLAN COTE ETAGE"), (60, "FACADE PRINCIPALE")):
        for k in range(12):
            msp.add_line((ox + k, 0), (ox + k, 10))
        msp.add_line((ox, 0), (ox + 11, 0))
        msp.add_text(title, dxfattribs={"insert": (ox + 3, -2), "height": 0.4})
    doc.saveas(tmp_path / "p.dxf")
    sheets = find_sheets(import_plan(str(tmp_path / "p.dxf")))
    assert [s.title for s in sheets] == ["PLAN COTE RDC", "PLAN COTE ETAGE", "FACADE PRINCIPALE"]
    assert [s.is_plan for s in sheets] == [True, True, False]


def test_free_wall_ends():
    walls = [(0, 0, 8, 0), (0, 6, 8, 6), (0, 0, 0, 6), (8, 0, 8, 6),
             (3, 0, 3, 1.2),     # retour de 1,2 m (trumeau) : pas de poteau au bout
             (5, 6, 5, 3)]       # refend de 3 m : poteau au bout
    b = structure_from_walls(walls, max_span=4.5)
    assert not any(abs(c.x - 3) < 0.05 and abs(c.y - 1.2) < 0.05 for c in b.columns)
    assert any(abs(c.x - 5) < 0.05 and abs(c.y - 3) < 0.05 for c in b.columns)


def test_light_roof_over_slab(tmp_path):
    proj = build_project(import_plan(write_duplex(tmp_path / "duplex.dxf")))
    dalle = run(proj, LoadSettings(), get_code("bael"), sigma_sol=0.2)
    charp = run(proj, LoadSettings(roof_type="charpente", g_roof_extra=0.6), get_code("bael"), sigma_sol=0.2)
    assert charp.loads.light_roof and not dalle.loads.light_roof
    assert charp.takedown.surface_g_roof == 0.6
    assert sum(f.design.nser for f in charp.footings) < sum(f.design.nser for f in dalle.footings)
