"""Export SAF (Structural Analysis Format, classeur Excel ouvert, version 2.0.0).

Lu par Graitec Advance Design, SCIA Engineer, Dlubal RFEM / RSTAB, SOFiSTiK, etc. Les
noms des feuilles et des colonnes suivent la spécification (saf.guide) et son fichier
d'exemple officiel.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from ..design import ProjectResult
from .analytical import AnalyticalModel, build_analytical

E_MODULUS = {"C20/25": 30000, "C25/30": 31000, "C30/37": 33000, "C35/45": 34000, "C40/50": 35000}

SHEETS: dict[str, list[str]] = {
    "StructuralMaterial": ["Name", "Type", "Subtype", "Quality", "Unit mass [kg/m3]", "E modulus [MPa]",
                           "G modulus [MPa]", "Poisson coefficient", "Thermal expansion [1/K]", "Design properties",
                           "Id"],
    "StructuralCrossSection": ["Name", "Material", "Cross-section Type", "Shape", "Parameters [mm]", "Profile",
                               "Form code", "Description ID of the profile", "A [m2]", "Iy [m4]", "Iz [m4]",
                               "It [m4]", "Iw [m6]", "Wply [m3]", "Wplz [m3]", "Id"],
    "StructuralPointConnection": ["Name", "Coordinate X [m]", "Coordinate Y [m]", "Coordinate Z [m]", "Id"],
    "StructuralCurveMember": ["Name", "Type", "Cross section", "Arbitrary definition", "Nodes", "Segments",
                              "Begin node", "End node", "Internal nodes", "Length [m]", "Geometrical shape", "LCS",
                              "LCS Rotation [deg]", "Coordinate X [m]", "Coordinate Y [m]", "Coordinate Z [m]",
                              "System line", "Structural Y Eccentricity of Beg Node [mm]",
                              "Structural Y Eccentricity of End Node [mm]", "Structural Z Eccentricity of Beg Node [mm]",
                              "Structural Z Eccentricity of End Node [mm]", "Analysis Y Eccentricity of Beg Node [mm]",
                              "Analysis Y Eccentricity of End Node [mm]", "Analysis Z Eccentricity of Beg Node [mm]",
                              "Analysis Z Eccentricity of End Node [mm]", "Layer", "Behaviour in analysis", "Color",
                              "Parent ID", "Id"],
    "StructuralStorey": ["Name", "Height level [m]", "Id"],
    "StructuralPointSupport": ["Name", "Type", "Node", "ux", "uy", "uz", "fix", "fiy", "fiz", "Stiffness X [MN/m]",
                               "Stiffness Y [MN/m]", "Stiffness Z [MN/m]", "Stiffness Fix [MNm/rad]",
                               "Stiffness Fiy [MNm/rad]", "Stiffness Fiz [MNm/rad]", "Id"],
    "StructuralLoadGroup": ["Name", "Load group type", "Relation", "Load type", "Id"],
    "StructuralLoadCase": ["Name", "Description", "Action type", "Load group", "Load type", "Duration", "Id"],
    "StructuralLoadCombination": ["Name", "Description", "Category", "National standard", "Load Factor 1",
                                  "Multiplier 1", "Load Case name 1", "Load Factor 2", "Multiplier 2",
                                  "Load Case name 2", "Load Factor 3", "Multiplier 3", "Load Case name 3", "Id"],
    "StructuralPointAction": ["Name", "Type", "Direction", "Force action", "Reference node", "Reference member",
                              "Value [kN]", "Vector (X;Y;Z) [kN]", "Load case", "Coordinate system", "Origin",
                              "Coordinate definition", "Position x [m]", "Repeat (n)", "Delta x [m]", "Id"],
    "StructuralCurveAction": ["Name", "Type", "Force action", "Distribution", "Direction", "Value 1 [kN/m]",
                              "Value 2 [kN/m]", "Vector 1(X;Y;Z) [kN/m]", "Vector 2(X;Y;Z) [kN/m]", "Member",
                              "Member rib", "2D Member", "2D Member Region", "2D Member Opening", "Edge",
                              "Internal edge", "Load case", "Coordinate system", "Location", "Coordinate definition",
                              "Origin", "Extent", "Start point [m]", "End point [m]", "Eccentricity ey [mm]",
                              "Eccentricity ez [mm]", "Parent ID", "Id"],
}


def _id() -> str:
    return str(uuid.uuid4())


def saf_tables(model: AnalyticalModel, national_code: str = "EC-NF-EN") -> tuple[list, list, dict]:
    """(feuille Project, feuille Model, {feuille: [lignes (dict)]})."""
    now = datetime.now().replace(microsecond=0)
    project = [("Name", model.name), ("Description", "Modèle analytique exporté par Koordin-IA"),
               ("Project nr", ""), ("Created", now), ("Last update", now), ("Project type", "Building construction"),
               ("Project kind", "New building"), ("Building type", ""), ("Status", "Design"), ("Location", ""),
               ("Id", _id())]
    meta = [("Name", model.name), ("Description", "Ossature béton armé (poteaux, poutres) et charges de plancher"),
            ("Discipline", "Load-bearing structure"), ("Level of detail", "Preliminary design"),
            ("Status", "In progress"), ("Owner", ""), ("Revision number", "1"), ("Created", now), ("Last update", now),
            ("Source type", "Software"), ("Source application", "Koordin-IA"), ("SAF Version", "2.0.0"),
            ("Source company", ""), ("Global coordinate system", "Z vertical"), ("LCS of cross-section", "ZYX"),
            ("System of units", "Metric"), ("National code", national_code), ("Ignored objects", ""),
            ("Ignored groups", ""), ("Id", _id())]
    t: dict[str, list[dict]] = {k: [] for k in SHEETS}
    t["StructuralMaterial"].append({"Name": "BETON", "Type": "Concrete", "Quality": model.concrete,
                                    "Unit mass [kg/m3]": 2500, "E modulus [MPa]": E_MODULUS.get(model.concrete, 31000),
                                    "G modulus [MPa]": round(E_MODULUS.get(model.concrete, 31000) / 2.4),
                                    "Poisson coefficient": 0.2, "Thermal expansion [1/K]": 1e-5, "Id": _id()})
    sec_names = {}
    for k, s in enumerate(model.sections.values(), start=1):
        name = f"CS{k}"
        sec_names[s.name] = name
        # Rectangle : « H; B » dans le repère local (z, y) de la section
        params = f"{s.b * 1000:.0f};{s.h * 1000:.0f}" if s.kind == "Column" else f"{s.h * 1000:.0f};{s.b * 1000:.0f}"
        t["StructuralCrossSection"].append({"Name": name, "Material": "BETON", "Cross-section Type": "Parametric",
                                            "Shape": "Rectangle", "Parameters [mm]": params,
                                            "A [m2]": round(s.b * s.h, 5), "Id": _id()})
    for n in model.nodes.values():
        t["StructuralPointConnection"].append({"Name": n.name, "Coordinate X [m]": n.x, "Coordinate Y [m]": n.y,
                                               "Coordinate Z [m]": n.z, "Id": _id()})
    for m in model.members:
        a, b = model.nodes[m.n1], model.nodes[m.n2]
        L = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
        col = m.kind == "Column"
        row = {"Name": m.name, "Type": m.kind, "Cross section": sec_names[m.section], "Nodes": f"{m.n1};{m.n2}",
               "Segments": "Line", "Begin node": m.n1, "End node": m.n2, "Internal nodes": "", "Length [m]": round(L, 3),
               "Geometrical shape": "Line", "LCS": "Y by vector" if col else "Z by vector", "LCS Rotation [deg]": 0,
               "Coordinate X [m]": 0, "Coordinate Y [m]": 1 if col else 0, "Coordinate Z [m]": 0 if col else 1,
               "System line": "Centre" if col else "Top", "Layer": f"{'Poteaux' if col else 'Poutres'} {m.storey + 1}",
               "Behaviour in analysis": "Standard", "Color": "#FF808080" if col else "#FF4080C0", "Id": _id()}
        for k in SHEETS["StructuralCurveMember"]:
            if "Eccentricity" in k:
                row[k] = 0
        row["Parent ID"] = None
        t["StructuralCurveMember"].append(row)
    for name, z in model.storeys:
        t["StructuralStorey"].append({"Name": name, "Height level [m]": z, "Id": _id()})
    for k, (n, kind, ref) in enumerate(model.supports, start=1):
        rot = "Rigid" if kind == "Fixed" else "Free"
        t["StructuralPointSupport"].append({"Name": f"Sn{k}", "Type": "Fixed" if kind == "Fixed" else "Hinged",
                                            "Node": n, "ux": "Rigid", "uy": "Rigid", "uz": "Rigid", "fix": rot,
                                            "fiy": rot, "fiz": rot, "Id": _id()})
    t["StructuralLoadGroup"] += [
        {"Name": "LG1", "Load group type": "Permanent", "Id": _id()},
        {"Name": "LG2", "Load group type": "Variable", "Relation": "Standard", "Load type": "Domestic", "Id": _id()}]
    t["StructuralLoadCase"] += [
        {"Name": "PP", "Description": "Poids propre", "Action type": "Permanent", "Load group": "LG1",
         "Load type": "Self weight", "Id": _id()},
        {"Name": "G", "Description": "Charges permanentes de plancher", "Action type": "Permanent",
         "Load group": "LG1", "Load type": "Others", "Id": _id()},
        {"Name": "Q", "Description": "Charges d'exploitation", "Action type": "Variable", "Load group": "LG2",
         "Load type": "Static", "Duration": "Medium", "Id": _id()}]
    for name, desc, cat, fg, fq in (("ELU", "1,35 G + 1,5 Q", "ULS (Ultimate Limit State)", 1.35, 1.5),
                                    ("ELS", "G + Q", "SLS (Serviceability Limit State)", 1.0, 1.0)):
        t["StructuralLoadCombination"].append({
            "Name": name, "Description": desc, "Category": cat, "Load Factor 1": fg, "Multiplier 1": 1,
            "Load Case name 1": "PP", "Load Factor 2": fg, "Multiplier 2": 1, "Load Case name 2": "G",
            "Load Factor 3": fq, "Multiplier 3": 1, "Load Case name 3": "Q", "Id": _id()})
    k = 0
    for case, rows in model.line_loads.items():
        for m, w in rows:
            k += 1
            t["StructuralCurveAction"].append({
                "Name": f"LF{k}", "Type": "Standard", "Force action": "On beam", "Distribution": "Uniform",
                "Direction": "Z", "Value 1 [kN/m]": -w, "Vector 1(X;Y;Z) [kN/m]": "", "Vector 2(X;Y;Z) [kN/m]": "",
                "Member": m, "Load case": case, "Coordinate system": "Global", "Location": "Length",
                "Coordinate definition": "Relative", "Origin": "From start", "Extent": "Full", "Start point [m]": 0,
                "End point [m]": 1, "Eccentricity ey [mm]": 0, "Eccentricity ez [mm]": 0, "Id": _id()})
    k = 0
    for case, rows in model.node_loads.items():
        for n, v in rows:
            k += 1
            t["StructuralPointAction"].append({
                "Name": f"F{k}", "Type": "Standard", "Direction": "Z", "Force action": "In node", "Reference node": n,
                "Value [kN]": -v, "Vector (X;Y;Z) [kN]": "", "Load case": case, "Coordinate system": "Global",
                "Id": _id()})
    return project, meta, t


def export_saf(res: ProjectResult, path: str | Path, model: AnalyticalModel | None = None) -> Path:
    from openpyxl import Workbook

    model = model or build_analytical(res)
    # BAEL : pas de code national SAF équivalent → Eurocode avec annexe française (combinaisons explicites)
    national = "EC-NF-EN"
    project, meta, tables = saf_tables(model, national)
    wb = Workbook()
    ws = wb.active
    ws.title = "Project"
    for row in project:
        ws.append(list(row))
    ws = wb.create_sheet("Model")
    for row in meta:
        ws.append(list(row))
    for sheet, header in SHEETS.items():
        rows = tables[sheet]
        if not rows:
            continue
        ws = wb.create_sheet(sheet)
        ws.append(header)
        for r in rows:
            ws.append([r.get(h) for h in header])
    path = Path(path)
    wb.save(path)
    return path
