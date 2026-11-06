"""Import des plans AutoCAD (DXF natif, DWG via ODA File Converter)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing as DxfDocument

from ..geometry import Drawing, Mark, Rect, Segment, Text, rect_from_points

# $INSUNITS -> facteur vers le mètre
_INSUNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
_UNIT_NAMES = {"mm": 0.001, "cm": 0.01, "m": 1.0}


class ImportErrorBatiCalc(RuntimeError):
    pass


def read_dwg_or_dxf(path: str | Path) -> DxfDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return ezdxf.readfile(path)
    if suffix == ".dwg" or _is_dwg(path):
        return _read_dwg(path)
    raise ImportErrorBatiCalc(f"Format non reconnu : {suffix}")


def _is_dwg(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"AC10" and path.suffix.lower() != ".dxf"
    except OSError:
        return False


def find_dwg2dxf() -> str | None:
    """Convertisseur LibreDWG : variable BATICALC_DWG2DXF, sinon `dwg2dxf` dans le PATH."""
    from .. import env as _env

    env = _env("DWG2DXF")
    if env and Path(env).exists():
        return env
    return shutil.which("dwg2dxf")


def _read_dwg(path: Path) -> DxfDocument:
    """Lecture DWG : ODA File Converter si installé, sinon LibreDWG (dwg2dxf)."""
    from ezdxf.addons import odafc

    if odafc.is_installed():
        return odafc.readfile(str(path))
    tool = find_dwg2dxf()
    if tool:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "plan.dwg"
            shutil.copyfile(path, src)
            dst = Path(tmp) / "plan.dxf"
            proc = subprocess.run([tool, "-y", "-o", str(dst), str(src)], capture_output=True, text=True,
                                  timeout=900)
            if not dst.exists():
                raise ImportErrorBatiCalc(f"Échec de la conversion DWG → DXF par LibreDWG :\n{proc.stderr[-800:]}")
            try:
                return ezdxf.readfile(dst)
            except ezdxf.DXFStructureError:
                from ezdxf import recover

                doc, _ = recover.readfile(dst)
                return doc
    raise ImportErrorBatiCalc(
        "Lecture DWG impossible : aucun convertisseur installé.\n"
        "  - LibreDWG (libre) : outil « dwg2dxf » dans le PATH, ou variable BATICALC_DWG2DXF ;\n"
        "  - ou ODA File Converter (gratuit) : https://www.opendesign.com/guestfiles/oda_file_converter ;\n"
        "  - ou, dans AutoCAD : ENREGSOUS (SAVEAS) → format DXF, puis relancez avec le .dxf."
    )


def _unit_factor(doc: DxfDocument, units: str | None) -> tuple[float, str | None]:
    if units:
        return _UNIT_NAMES[units], None
    code = doc.header.get("$INSUNITS", 0)
    if code in _INSUNITS:
        return _INSUNITS[code], None
    # Unité non définie : on la déduit de l'étendue du dessin
    try:
        from ezdxf import bbox

        ext = bbox.extents(doc.modelspace(), fast=True)
        size = max(ext.size.x, ext.size.y) if ext.has_data else 0
    except Exception:  # pragma: no cover - sécurité
        size = 0
    if size > 2000:
        f, name = 0.001, "mm"
    elif size > 200:
        f, name = 0.01, "cm"
    else:
        f, name = 1.0, "m"
    return f, f"Unités du DXF non définies : supposées en {name} (forcer avec --unites)."


def _iter_entities(entities, depth: int = 0, blocks: list | None = None):
    for e in entities:
        if e.dxftype() == "INSERT" and depth < 6:
            parent_layer = e.dxf.layer
            if blocks is not None:
                blocks.append(e)
            try:
                children = list(e.virtual_entities())
            except Exception:
                continue
            for child in children:
                if child.dxf.layer == "0":
                    child.dxf.layer = parent_layer
            yield from _iter_entities(children, depth + 1, blocks)
        else:
            yield e


def import_dxf(path: str | Path, units: str | None = None) -> Drawing:
    doc = read_dwg_or_dxf(path)
    k, warn = _unit_factor(doc, units)
    out = Drawing(source=str(path))
    if warn:
        out.warnings.append(warn)

    layer_lt = {l.dxf.name.upper(): (l.dxf.get("linetype", "Continuous") or "Continuous").upper() for l in doc.layers}

    def is_dashed(e) -> bool:
        lt = (e.dxf.get("linetype", "BYLAYER") or "BYLAYER").upper()
        if lt == "BYLAYER":
            lt = layer_lt.get(e.dxf.get("layer", "0").upper(), "CONTINUOUS")
        return lt not in ("CONTINUOUS", "CONTINU", "BYBLOCK", "")

    def add_poly(pts: list[tuple[float, float]], closed: bool, layer: str, filled: bool = False,
                 dashed: bool = False) -> None:
        pts = [(x * k, y * k) for x, y in pts]
        r = rect_from_points(pts, tol=0.005) if (closed or (len(pts) == 5 and pts[0] == pts[-1])) else None
        if r:
            out.rects.append(Rect(*r, layer=layer, filled=filled))
            return
        n = len(pts)
        for i in range(n - 1 + (1 if closed else 0)):
            a, b = pts[i], pts[(i + 1) % n]
            out.segments.append(Segment(a[0], a[1], b[0], b[1], layer, dashed))

    inserts: list = []
    for e in _iter_entities(doc.modelspace(), blocks=inserts):
        t = e.dxftype()
        layer = e.dxf.get("layer", "0").upper()
        try:
            if t == "LINE":
                s, d = e.dxf.start, e.dxf.end
                out.segments.append(Segment(s.x * k, s.y * k, d.x * k, d.y * k, layer, is_dashed(e)))
            elif t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                add_poly(pts, e.closed, layer, dashed=is_dashed(e))
            elif t == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                add_poly(pts, e.is_closed, layer, dashed=is_dashed(e))
            elif t in ("SOLID", "TRACE"):
                pts = [(e.dxf.get(f"vtx{i}").x, e.dxf.get(f"vtx{i}").y) for i in range(4)]
                add_poly(pts, True, layer, filled=True)
            elif t == "HATCH":
                for p in e.paths:
                    if hasattr(p, "vertices"):
                        pts = [(v[0], v[1]) for v in p.vertices]
                    else:
                        pts = [(ed.start[0], ed.start[1]) for ed in p.edges if hasattr(ed, "start")]
                    if pts:
                        add_poly(pts, True, layer, filled=True)
            elif t == "TEXT":
                ins = e.dxf.insert
                out.texts.append(Text(ins.x * k, ins.y * k, e.dxf.text, layer))
            elif t == "MTEXT":
                ins = e.dxf.insert
                out.texts.append(Text(ins.x * k, ins.y * k, e.plain_text(), layer))
            elif t in ("CIRCLE", "ARC"):
                c, r = e.dxf.center, e.dxf.radius
                out.marks.append(Mark((c.x - r) * k, (c.y - r) * k, (c.x + r) * k, (c.y + r) * k, layer, t))
            elif t == "ELLIPSE":
                c, ma = e.dxf.center, e.dxf.major_axis
                r = (ma.x ** 2 + ma.y ** 2) ** 0.5
                out.marks.append(Mark((c.x - r) * k, (c.y - r) * k, (c.x + r) * k, (c.y + r) * k, layer, t))
        except Exception:  # entité malformée : on l'ignore
            continue
    return out
