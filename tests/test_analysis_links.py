"""Liens directs vers les logiciels de calcul : modèle analytique, SAF (Graitec…), script Robot."""
import csv
import math
import runpy
import sys
import types

import openpyxl
import pytest

from baticalc.codes import get_code
from baticalc.design import run
from baticalc.importers import import_plan
from baticalc.interop.analytical import build_analytical
from baticalc.interop.robot_export import base_loads, compare_reactions, export_robot
from baticalc.interop.saf_export import SHEETS, export_saf
from baticalc.model import LoadSettings
from baticalc.recognition import build_model

from test_zones import write_rooms_dxf


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    d = tmp_path_factory.mktemp("liens")
    bld = build_model(import_plan(write_rooms_dxf(d / "l.dxf")), n_levels=3, floor_height=3.0)
    return run(bld, LoadSettings(continuity=False, degression=False), get_code("bael"))


def _length(model, m):
    a, b = model.nodes[m.n1], model.nodes[m.n2]
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def test_analytical_model(result):
    m = build_analytical(result)
    cols = [x for x in m.members if x.kind == "Column"]
    assert len(cols) == 9 * 3
    # barres raccordées : chaque extrémité est un nœud existant, aucune barre de longueur nulle
    assert all(x.n1 in m.nodes and x.n2 in m.nodes and _length(m, x) > 0.05 for x in m.members)
    # 9 encastrements en pied
    assert sum(1 for s in m.supports if s[1] == "Fixed") == 9
    # équilibre : Q appliqué = Q en pied de poteaux (sans dégression)
    mm = m.member_map()
    q_tot = sum(w * _length(m, mm[n]) for n, w in m.line_loads["Q"]) + sum(v for _, v in m.node_loads["Q"])
    base = base_loads(result)
    assert q_tot == pytest.approx(sum(v["Q"] for v in base.values()), rel=1e-3)


def test_saf_export(result, tmp_path):
    p = export_saf(result, tmp_path / "modele.xlsx")
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames[:2] == ["Project", "Model"]
    model_info = {r[0]: r[1] for r in wb["Model"].iter_rows(values_only=True)}
    assert model_info["SAF Version"] == "2.0.0" and model_info["Global coordinate system"] == "Z vertical"

    def table(name):
        rows = list(wb[name].iter_rows(values_only=True))
        assert list(rows[0]) == SHEETS[name]
        return [dict(zip(rows[0], r)) for r in rows[1:]]

    nodes = {r["Name"] for r in table("StructuralPointConnection")}
    secs = {r["Name"]: r for r in table("StructuralCrossSection")}
    assert all(s["Shape"] == "Rectangle" and ";" in s["Parameters [mm]"] for s in secs.values())
    members = table("StructuralCurveMember")
    assert {r["Type"] for r in members} == {"Column", "Beam"}
    for r in members:
        a, b = r["Nodes"].split(";")
        assert a in nodes and b in nodes and r["Cross section"] in secs
    assert all(r["Node"] in nodes for r in table("StructuralPointSupport"))
    cases = {r["Name"] for r in table("StructuralLoadCase")}
    assert cases == {"PP", "G", "Q"}
    names = {r["Name"] for r in members}
    acts = table("StructuralCurveAction")
    assert acts and all(r["Member"] in names and r["Load case"] in cases and r["Value 1 [kN/m]"] < 0 for r in acts)
    combos = table("StructuralLoadCombination")
    assert combos[0]["Category"].startswith("ULS") and combos[0]["Load Factor 3"] == 1.5


class _Any:
    """Imitation minimale de l'API RobotOM : enregistre les appels, tout attribut existe."""

    log: list = []

    def __init__(self, name="R"):
        self._name = name

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return _Any(f"{self._name}.{item}")

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    def __call__(self, *a, **k):
        _Any.log.append((self._name, a))
        if self._name.endswith("Reactions.Value"):
            return types.SimpleNamespace(FZ=1000.0 * (10 if a[1] == 1 else 5))
        if self._name.endswith("Records.New"):
            return 1
        return _Any(self._name + "()")


def test_robot_script_runs_against_api_stub(result, tmp_path, monkeypatch):
    py, bat, js, zp = export_robot(result, tmp_path)
    assert zp.name == "robot_baticalc.zip"
    assert bat.read_bytes().startswith(b"@echo off")
    _Any.log = []
    monkeypatch.setitem(sys.modules, "clr", types.SimpleNamespace(AddReference=lambda p: None))
    monkeypatch.setitem(sys.modules, "RobotOM", _Any("R"))
    monkeypatch.setenv("ROBOT_DLL", "Interop.RobotOM.dll")
    runpy.run_path(str(py), run_name="__main__")
    m = build_analytical(result)
    calls = [c for c, _ in _Any.log]
    assert sum(c.endswith("Nodes.Create") for c in calls) == len(m.nodes)
    assert sum(c.endswith("Bars.Create") for c in calls) == len(m.members)
    assert any(c.endswith("CalcEngine.Calculate") for c in calls)
    # charges en N : signe et facteur 1000
    pz = [a[1] for c, a in _Any.log if c.endswith("rec.SetValue") or c.endswith(").SetValue")]
    assert pz
    reac = tmp_path / "robot" / "robot_reactions.csv"
    rows = list(csv.DictReader(open(reac, encoding="utf-8"), delimiter=";"))
    assert len(rows) == 3 * len(m.supports)
    cmp = compare_reactions(base_loads(result), reac)
    assert cmp[0]["robot_G"] == pytest.approx(15.0) and cmp[0]["robot_Q"] == pytest.approx(5.0)
    assert cmp[0]["baticalc_G"] > 0
