"""Export IFC4 du modèle de structure (vue « Reference View » : géométrie + propriétés).

Fichier lisible par Revit, ArchiCAD, Tekla, Robot Structural Analysis, CYPECAD,
Graitec Advance / Arche, BIMcollab, etc. Contenu :
- projet / site / bâtiment / niveaux (altitudes) ;
- poteaux (IfcColumn), poutres et poutres de transfert (IfcBeam), planchers (IfcSlab),
  semelles (IfcFooting), avec géométrie extrudée et matériau béton ;
- résultats de dimensionnement dans un jeu de propriétés « BatiCalc_Dimensionnement »
  (section, armatures, cadres, effort, vérification) et quantités (volumes, longueurs).
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid

from ..design import ProjectResult


class _Writer:
    def __init__(self, name: str):
        self.f = ifcopenshell.file(schema="IFC4")
        f = self.f
        self.origin = f.createIfcCartesianPoint((0.0, 0.0, 0.0))
        self.z = f.createIfcDirection((0.0, 0.0, 1.0))
        self.x = f.createIfcDirection((1.0, 0.0, 0.0))
        self.world = f.createIfcAxis2Placement3D(self.origin, self.z, self.x)
        ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0e-5, self.world, None)
        self.body = f.createIfcGeometricRepresentationSubContext("Body", "Model", None, None, None, None, ctx,
                                                                 None, "MODEL_VIEW", None)
        units = f.createIfcUnitAssignment([
            f.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
            f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
            f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"),
            f.createIfcSIUnit(None, "PLANEANGLEUNIT", None, "RADIAN"),
            f.createIfcSIUnit(None, "MASSUNIT", "KILO", "GRAM"),
            f.createIfcSIUnit(None, "FORCEUNIT", "KILO", "NEWTON"),
        ])
        app = f.createIfcApplication(
            f.createIfcOrganization(None, "BatiCalc", None, None, None), "0.3", "BatiCalc", "BatiCalc")
        person = f.createIfcPerson(None, None, "BatiCalc", None, None, None, None, None)
        org = f.createIfcOrganization(None, "BatiCalc", None, None, None)
        self.owner = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(person, org, None), app, None,
                                             "ADDED", None, None, None, int(time.time()))
        self.project = f.createIfcProject(self.guid(), self.owner, name or "Projet BatiCalc", None, None, None,
                                          None, [ctx], units)
        self.material = f.createIfcMaterial("Béton armé", None, "Concrete")

    @staticmethod
    def guid() -> str:
        return ifcopenshell.guid.new()

    def placement(self, parent, x=0.0, y=0.0, z=0.0, zdir=None, xdir=None):
        f = self.f
        axis = f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((float(x), float(y), float(z))),
            f.createIfcDirection(tuple(float(v) for v in zdir)) if zdir else None,
            f.createIfcDirection(tuple(float(v) for v in xdir)) if xdir else None)
        return f.createIfcLocalPlacement(parent, axis)

    def rect_solid(self, xdim, ydim, depth, cx=0.0, cy=0.0, z0=0.0):
        f = self.f
        prof = f.createIfcRectangleProfileDef(
            "AREA", None, f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((float(cx), float(cy))), None),
            float(xdim), float(ydim))
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z0))), None, None)
        return f.createIfcExtrudedAreaSolid(prof, pos, self.z, float(depth))

    def shape(self, items):
        rep = self.f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", items)
        return self.f.createIfcProductDefinitionShape(None, None, [rep])

    def props(self, element, name: str, values: dict) -> None:
        f = self.f
        props = []
        for k, v in values.items():
            if v is None or v == "":
                continue
            if isinstance(v, bool):
                nv = f.createIfcBoolean(v)
            elif isinstance(v, (int, float)):
                nv = f.createIfcReal(float(v))
            else:
                nv = f.createIfcLabel(str(v))
            props.append(f.createIfcPropertySingleValue(k, None, nv, None))
        if props:
            pset = f.createIfcPropertySet(self.guid(), self.owner, name, None, props)
            f.createIfcRelDefinesByProperties(self.guid(), self.owner, None, None, [element], pset)

    def quantities(self, element, name: str, values: dict) -> None:
        f = self.f
        qs = []
        for k, (kind, v) in values.items():
            if kind == "L":
                qs.append(f.createIfcQuantityLength(k, None, None, float(v), None))
            elif kind == "A":
                qs.append(f.createIfcQuantityArea(k, None, None, float(v), None))
            elif kind == "V":
                qs.append(f.createIfcQuantityVolume(k, None, None, float(v), None))
            elif kind == "W":
                qs.append(f.createIfcQuantityWeight(k, None, None, float(v), None))
        if qs:
            q = f.createIfcElementQuantity(self.guid(), self.owner, name, None, None, qs)
            f.createIfcRelDefinesByProperties(self.guid(), self.owner, None, None, [element], q)


SLAB_THICKNESS = {"corps_creux": 0.20, "dalle_pleine": 0.18}


def export_ifc(res: ProjectResult, path: str | Path) -> Path:
    from ..outputs.viewer import _rects, viewer_data

    data = viewer_data(res)
    proj = res.project
    w = _Writer(proj.name or Path(proj.source.split(" (")[0]).stem)
    f = w.f
    site_pl = w.placement(None)
    site = f.createIfcSite(w.guid(), w.owner, "Site", None, None, site_pl, None, None, "ELEMENT",
                           None, None, None, None, None)
    bld_pl = w.placement(site_pl)
    building = f.createIfcBuilding(w.guid(), w.owner, "Bâtiment", None, None, bld_pl, None, None, "ELEMENT",
                                   None, None, None)
    f.createIfcRelAggregates(w.guid(), w.owner, None, None, w.project, [site])
    f.createIfcRelAggregates(w.guid(), w.owner, None, None, site, [building])
    slab_t = SLAB_THICKNESS.get(res.loads.floor_type, 0.20)
    storeys = []
    all_elements = []
    code = res.code.name
    for k, lv in enumerate(data["niveaux"]):
        st_pl = w.placement(bld_pl, 0, 0, lv["altitude"])
        st = f.createIfcBuildingStorey(w.guid(), w.owner, lv["nom"], lv["planche"] or None, None, st_pl, None,
                                       lv["nom"], "ELEMENT", float(lv["altitude"]))
        storeys.append(st)
        contained = []
        H = lv["hauteur"]
        for c in lv["colonnes"]:
            el = f.createIfcColumn(w.guid(), w.owner, c["id"], None, "Poteau BA",
                                   w.placement(st_pl, c["x"], c["y"], 0),
                                   w.shape([w.rect_solid(c["b"], c["h"], H)]), c["id"], "COLUMN")
            w.props(el, "Pset_ColumnCommon", {"Reference": c["id"], "LoadBearing": True})
            w.props(el, "BatiCalc_Dimensionnement", {
                "Section": f"{c['b'] * 100:.0f}x{c['h'] * 100:.0f} cm", "Armatures": c["armatures"],
                "Cadres": c["cadres"], "Nu_kN": c["nu"], "Verifie": c["ok"], "Reglement": code})
            w.quantities(el, "Qto_ColumnBaseQuantities", {"Length": ("L", H), "NetVolume": ("V", c["b"] * c["h"] * H)})
            contained.append(el)
        for b in lv["poutres"]:
            L = math.hypot(b["x2"] - b["x1"], b["y2"] - b["y1"])
            if L < 0.05:
                continue
            ux, uy = (b["x2"] - b["x1"]) / L, (b["y2"] - b["y1"]) / L
            pl = w.placement(st_pl, b["x1"], b["y1"], H - b["h"] / 2, zdir=(ux, uy, 0.0), xdir=(-uy, ux, 0.0))
            kind = "Poutre de transfert" if b.get("transfert") else "Poutre BA"
            el = f.createIfcBeam(w.guid(), w.owner, b["id"], None, kind, pl,
                                 w.shape([w.rect_solid(b["b"], b["h"], L)]), b["id"], "BEAM")
            w.props(el, "Pset_BeamCommon", {"Reference": b["id"], "LoadBearing": True, "Span": L})
            w.props(el, "BatiCalc_Dimensionnement", {
                "Section": f"{b['b'] * 100:.0f}x{b['h'] * 100:.0f} cm", "Aciers_inferieurs": b["inf"],
                "Aciers_superieurs": b["sup"], "Cadres": b["cadres"], "Transfert": bool(b.get("transfert")),
                "Creee_automatiquement": bool(b.get("auto")), "Verifie": b["ok"], "Reglement": code})
            w.quantities(el, "Qto_BeamBaseQuantities", {"Length": ("L", L), "NetVolume": ("V", b["b"] * b["h"] * L)})
            contained.append(el)
        rects = _rects(proj.storeys[k].plan.slab, step=0.10)  # résolution exacte du modèle
        if res.loads.light_roof and k == len(data["niveaux"]) - 1:
            rects = []   # toiture légère : pas de dalle
        if rects:
            lv = dict(lv, dalle=rects)
            items = [w.rect_solid(r[2] - r[0], r[3] - r[1], slab_t, (r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
                     for r in lv["dalle"]]
            el = f.createIfcSlab(w.guid(), w.owner, lv["plancher"], None,
                                 "Plancher " + ("corps creux" if res.loads.floor_type == "corps_creux" else "dalle pleine"),
                                 w.placement(st_pl, 0, 0, H - slab_t), w.shape(items), None,
                                 "ROOF" if k == len(data["niveaux"]) - 1 else "FLOOR")
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in lv["dalle"])
            w.props(el, "Pset_SlabCommon", {"LoadBearing": True, "IsExternal": k == len(data["niveaux"]) - 1})
            w.quantities(el, "Qto_SlabBaseQuantities", {"GrossArea": ("A", area), "Depth": ("L", slab_t)})
            contained.append(el)
        if k == 0:
            for ft in data["semelles"]:
                el = f.createIfcFooting(w.guid(), w.owner, f"S-{ft['id']}", None, "Semelle isolée",
                                        w.placement(st_pl, ft["x"], ft["y"], -ft["h"]),
                                        w.shape([w.rect_solid(ft["A"], ft["B"], ft["h"])]), ft["id"], "PAD_FOOTING")
                w.props(el, "BatiCalc_Dimensionnement", {"Dimensions": f"{ft['A'] * 100:.0f}x{ft['B'] * 100:.0f}x"
                                                        f"{ft['h'] * 100:.0f} cm", "Sous_mur": ft["sous_mur"],
                                                        "Contrainte_sol_MPa": res.sigma_sol, "Verifie": ft["ok"]})
                w.quantities(el, "Qto_FootingBaseQuantities", {"NetVolume": ("V", ft["A"] * ft["B"] * ft["h"])})
                contained.append(el)
        if contained:
            f.createIfcRelContainedInSpatialStructure(w.guid(), w.owner, None, None, contained, st)
            all_elements += contained
    f.createIfcRelAggregates(w.guid(), w.owner, None, None, building, storeys)
    if all_elements:
        f.createIfcRelAssociatesMaterial(w.guid(), w.owner, None, None, all_elements, w.material)
    path = Path(path)
    f.write(str(path))
    return path
