"""Lien direct avec Autodesk Robot Structural Analysis (API COM « RobotOM »).

Produit, dans le dossier des résultats :
- `robot/robot_modele.py` : script autonome qui ouvre Robot, crée le modèle (nœuds, barres,
  sections béton, appuis, cas PP / G / Q, combinaisons ELU / ELS), lance le calcul,
  enregistre le projet `.rtd` et exporte les réactions d'appui (`robot_reactions.csv`) ;
- `robot/lancer_robot.bat` : installe pythonnet si besoin et lance le script (Windows) ;
- `robot/robot_modele.json` : le modèle analytique (repères BatiCalc des nœuds et barres).

Ensuite `baticalc robot-comparer` compare les réactions de Robot à la descente de charges
de BatiCalc, poteau par poteau.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from ..design import ProjectResult
from .analytical import AnalyticalModel, build_analytical

SCRIPT = r'''# -*- coding: utf-8 -*-
"""Modèle BatiCalc → Autodesk Robot Structural Analysis (API RobotOM).

Utilisation (Windows, Robot installé) :  py -m pip install pythonnet  puis  py robot_modele.py
Variable d'environnement facultative ROBOT_DLL : chemin de Interop.RobotOM.dll.
"""
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = json.loads(open(os.path.join(HERE, "robot_modele.json"), encoding="utf-8").read())


def find_dll():
    if os.environ.get("ROBOT_DLL"):
        return os.environ["ROBOT_DLL"]
    pats = [r"C:\Program Files\Autodesk\Robot Structural Analysis Professional *\Exe\Interop.RobotOM.dll",
            r"C:\Program Files\Autodesk\Autodesk Robot Structural Analysis Professional *\Exe\Interop.RobotOM.dll",
            r"C:\Program Files (x86)\Common Files\Autodesk Shared\Structures\*\Interop.RobotOM.dll"]
    found = sorted(f for p in pats for f in glob.glob(p))
    if not found:
        sys.exit("Interop.RobotOM.dll introuvable : installez Robot ou définissez ROBOT_DLL.")
    return found[-1]


import clr  # noqa: E402  (pythonnet)

clr.AddReference(find_dll())
import RobotOM as R  # noqa: E402


def enum(cls, *names):
    for n in names:
        if hasattr(cls, n):
            return getattr(cls, n)
    raise AttributeError(f"{cls}: {names}")


app = R.RobotApplicationClass()
app.Visible = 1
app.Interactive = 1
app.Project.New(R.IRobotProjectType.I_PT_FRAME_3D)
st = app.Project.Structure
labels = st.Labels
KN = 1000.0  # l'API travaille en unités SI (N, m)

print("Nœuds…")
num = {}
for k, (name, n) in enumerate(MODEL["nodes"].items(), start=1):
    st.Nodes.Create(k, n["x"], n["y"], n["z"])
    num[name] = k

print("Sections…")
for s in MODEL["sections"].values():
    lab = labels.Create(R.IRobotLabelType.I_LT_BAR_SECTION, s["name"])
    data = R.IRobotBarSectionData(lab.Data)
    conc = None
    try:
        if s["kind"] == "Column":
            data.ShapeType = enum(R.IRobotBarSectionShapeType, "I_BSST_CONCR_COL_R")
            conc = R.IRobotBarSectionConcreteData(data.Concrete)
            conc.SetValue(enum(R.IRobotBarSectionConcreteDataValue, "I_BSCDV_COL_B"), s["b"])
            conc.SetValue(enum(R.IRobotBarSectionConcreteDataValue, "I_BSCDV_COL_H"), s["h"])
        else:
            raise AttributeError
    except AttributeError:
        data.ShapeType = R.IRobotBarSectionShapeType.I_BSST_CONCR_BEAM_RECT
        conc = R.IRobotBarSectionConcreteData(data.Concrete)
        conc.SetValue(R.IRobotBarSectionConcreteDataValue.I_BSCDV_BEAM_B, s["b"])
        conc.SetValue(R.IRobotBarSectionConcreteDataValue.I_BSCDV_BEAM_H, s["h"])
    data.CalcNonstdGeometry()
    labels.Store(lab)

print("Barres…")
bar_num = {}
for k, m in enumerate(MODEL["members"], start=1):
    st.Bars.Create(k, num[m["n1"]], num[m["n2"]])
    bar = R.IRobotBar(st.Bars.Get(k))
    bar.SetLabel(R.IRobotLabelType.I_LT_BAR_SECTION, m["section"])
    try:
        bar.SetLabel(R.IRobotLabelType.I_LT_MATERIAL, MODEL["concrete"])
    except Exception:
        pass  # matériau béton par défaut des préférences Robot
    bar_num[m["name"]] = k

print("Appuis…")
for kind, rot in (("Fixed", 1), ("Hinged", 0)):
    lab = labels.Create(R.IRobotLabelType.I_LT_SUPPORT, "Encastrement" if rot else "Articulation")
    d = R.IRobotNodeSupportData(lab.Data)
    d.UX = d.UY = d.UZ = 1
    d.RX = d.RY = d.RZ = rot
    labels.Store(lab)
for n, kind, ref in MODEL["supports"]:
    node = R.IRobotNode(st.Nodes.Get(num[n]))
    node.SetLabel(R.IRobotLabelType.I_LT_SUPPORT, "Encastrement" if kind == "Fixed" else "Articulation")

print("Charges…")
NAT = R.IRobotCaseNature
AN = R.IRobotCaseAnalizeType
cases = {}
for k, (name, nature) in enumerate((("PP", NAT.I_CN_PERMANENT), ("G", NAT.I_CN_PERMANENT),
                                    ("Q", enum(NAT, "I_CN_EXPLOATATION", "I_CN_EXPLOITATION"))), start=1):
    cases[name] = (k, R.IRobotSimpleCase(st.Cases.CreateSimple(k, name, nature, AN.I_CAT_STATIC_LINEAR)))
case = cases["PP"][1]
rec = R.IRobotLoadRecord(case.Records.Get(case.Records.New(R.IRobotLoadRecordType.I_LRT_DEAD)))
rec.SetValue(R.IRobotDeadRecordValues.I_DRV_Z, -1)
rec.SetValue(R.IRobotDeadRecordValues.I_DRV_ENTIRE_STRUCTURE, True)
for cname in ("G", "Q"):
    case = cases[cname][1]
    for m, w in MODEL["line_loads"].get(cname, []):
        rec = R.IRobotLoadRecord(case.Records.Get(case.Records.New(R.IRobotLoadRecordType.I_LRT_BAR_UNIFORM)))
        rec.SetValue(R.IRobotBarUniformRecordValues.I_BURV_PZ, -w * KN)
        rec.Objects.FromText(str(bar_num[m]))
    for n, v in MODEL["node_loads"].get(cname, []):
        rec = R.IRobotLoadRecord(case.Records.Get(case.Records.New(R.IRobotLoadRecordType.I_LRT_NODE_FORCE)))
        rec.SetValue(R.IRobotNodeForceRecordValues.I_NFRV_FZ, -v * KN)
        rec.Objects.FromText(str(num[n]))
try:
    for k, (name, ctype, fg, fq) in enumerate((("ELU", R.IRobotCombinationType.I_CBT_ULS, 1.35, 1.5),
                                               ("ELS", R.IRobotCombinationType.I_CBT_SLS, 1.0, 1.0)), start=4):
        comb = st.Cases.CreateCombination(k, name, ctype, NAT.I_CN_PERMANENT, AN.I_CAT_COMB)
        comb.CaseFactors.New(cases["PP"][0], fg)
        comb.CaseFactors.New(cases["G"][0], fg)
        comb.CaseFactors.New(cases["Q"][0], fq)
except Exception as exc:  # combinaisons : à créer à la main si l'API diffère
    print("Combinaisons non créées :", exc)

print("Calcul…")
app.Project.CalcEngine.Calculate()
out = os.path.join(HERE, "robot_reactions.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["noeud", "repere", "cas", "FZ_kN"])
    for n, kind, ref in MODEL["supports"]:
        for cname, (k, _) in cases.items():
            r = st.Results.Nodes.Reactions.Value(num[n], k)
            w.writerow([n, ref, cname, round(r.FZ / KN, 2)])
app.Project.SaveAs(os.path.join(HERE, "modele_baticalc.rtd"))
print("Terminé :", out)
'''

BAT = "@echo off\r\ncd /d %~dp0\r\npy -m pip install --quiet pythonnet\r\npy robot_modele.py\r\npause\r\n"


def export_robot(res: ProjectResult, folder: str | Path, model: AnalyticalModel | None = None) -> list[Path]:
    model = model or build_analytical(res)
    folder = Path(folder) / "robot"
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "name": model.name, "concrete": model.concrete,
        "nodes": {k: asdict(v) for k, v in model.nodes.items()},
        "sections": {k: asdict(v) for k, v in model.sections.items()},
        "members": [asdict(m) for m in model.members],
        "supports": [list(s) for s in model.supports],
        "line_loads": model.line_loads, "node_loads": model.node_loads, "notes": model.notes,
    }
    js = folder / "robot_modele.json"
    js.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    py = folder / "robot_modele.py"
    py.write_text(SCRIPT, encoding="utf-8")
    bat = folder / "lancer_robot.bat"
    bat.write_bytes(BAT.encode("ascii"))
    # archive à télécharger (application web) : les trois fichiers à décompresser dans un même dossier
    import zipfile

    zp = folder.parent / "robot_baticalc.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (py, bat, js):
            z.write(f, f.name)
    return [py, bat, js, zp]


def base_loads(res: ProjectResult) -> dict[str, dict[str, float]]:
    """Charges en pied des poteaux du niveau bas (kN, poids propre compris, Q sans dégression)."""
    out = {}
    for cid, v in res.takedown.columns.items():
        s = next((s for s in v if s.storey == 1), None)
        if s:
            out[cid] = {"G": round(s.g, 2), "Q": round(s.q_raw, 2)}
    return out


def compare_reactions(base: dict[str, dict[str, float]], csv_path: str | Path) -> list[dict]:
    """Réactions de Robot (PP + G, Q) / charges en pied de poteau de BatiCalc (même découpage)."""
    robot: dict[str, dict[str, float]] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            robot.setdefault(row["repere"], {}).setdefault(row["cas"], 0.0)
            robot[row["repere"]][row["cas"]] += float(row["FZ_kN"])
    out = []
    for ref, cases in sorted(robot.items(), key=lambda kv: (len(kv[0]), kv[0])):
        r_g = cases.get("PP", 0.0) + cases.get("G", 0.0)
        r_q = cases.get("Q", 0.0)
        k = base.get(ref)
        tot = (k["G"] + k["Q"]) if k else 0.0
        out.append({"poteau": ref, "robot_G": round(r_g, 1), "robot_Q": round(r_q, 1),
                    "baticalc_G": k["G"] if k else None, "baticalc_Q": k["Q"] if k else None,
                    "ecart_pct": round(((r_g + r_q) / tot - 1) * 100, 1) if tot else None})
    return out
