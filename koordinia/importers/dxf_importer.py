"""Import des plans AutoCAD (DXF natif, DWG via ODA File Converter)."""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.document import Drawing as DxfDocument

from ..geometry import Drawing, Rect, Segment, Text, rect_from_points

# $INSUNITS -> facteur vers le mètre
_INSUNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
_UNIT_NAMES = {"mm": 0.001, "cm": 0.01, "m": 1.0}


class ImportErrorKoordinia(RuntimeError):
    pass


def read_dwg_or_dxf(path: str | Path) -> DxfDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return ezdxf.readfile(path)
    if suffix == ".dwg":
        from ezdxf.addons import odafc

        if not odafc.is_installed():
            raise ImportErrorKoordinia(
                "Lecture DWG impossible : le convertisseur gratuit « ODA File Converter » n'est pas installé.\n"
                "  - Installez-le : https://www.opendesign.com/guestfiles/oda_file_converter\n"
                "  - ou, dans AutoCAD : commande ENREGSOUS (SAVEAS) → format DXF, puis relancez avec le .dxf."
            )
        return odafc.readfile(str(path))
    raise ImportErrorKoordinia(f"Format non reconnu : {suffix}")


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


def _iter_entities(entities, depth: int = 0):
    for e in entities:
        if e.dxftype() == "INSERT" and depth < 6:
            parent_layer = e.dxf.layer
            try:
                children = list(e.virtual_entities())
            except Exception:
                continue
            for child in children:
                if child.dxf.layer == "0":
                    child.dxf.layer = parent_layer
            yield from _iter_entities(children, depth + 1)
        else:
            yield e


def import_dxf(path: str | Path, units: str | None = None) -> Drawing:
    doc = read_dwg_or_dxf(path)
    k, warn = _unit_factor(doc, units)
    out = Drawing(source=str(path))
    if warn:
        out.warnings.append(warn)

    def add_poly(pts: list[tuple[float, float]], closed: bool, layer: str, filled: bool = False) -> None:
        pts = [(x * k, y * k) for x, y in pts]
        r = rect_from_points(pts, tol=0.005) if (closed or (len(pts) == 5 and pts[0] == pts[-1])) else None
        if r:
            out.rects.append(Rect(*r, layer=layer, filled=filled))
            return
        n = len(pts)
        for i in range(n - 1 + (1 if closed else 0)):
            a, b = pts[i], pts[(i + 1) % n]
            out.segments.append(Segment(a[0], a[1], b[0], b[1], layer))

    for e in _iter_entities(doc.modelspace()):
        t = e.dxftype()
        layer = e.dxf.get("layer", "0").upper()
        try:
            if t == "LINE":
                s, d = e.dxf.start, e.dxf.end
                out.segments.append(Segment(s.x * k, s.y * k, d.x * k, d.y * k, layer))
            elif t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                add_poly(pts, e.closed, layer)
            elif t == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                add_poly(pts, e.is_closed, layer)
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
        except Exception:  # entité malformée : on l'ignore
            continue
    return out
