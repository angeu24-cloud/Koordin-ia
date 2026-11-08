"""Importeurs de plans : DWG/DXF (AutoCAD), PDF vectoriel, plans scannés (images, PDF image)."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..geometry import Drawing


def import_plan(path, *, units: str | None = None, scale: int | None = None, page: int = 1,
                px_per_m: float | None = None) -> Drawing:
    if isinstance(path, (list, tuple)):
        if len(path) == 1:
            path = path[0]
        else:
            return import_plans(path, units=units, scale=scale, page=page, px_per_m=px_per_m)
    suffix = Path(path).suffix.lower()
    try:
        with open(path, "rb") as f:
            magic = f.read(6)
    except OSError:
        magic = b""
    if suffix in (".dwg", ".dxf") or magic.startswith(b"AC10"):
        from .dxf_importer import import_dxf

        return import_dxf(path, units=units)
    from .raster_importer import IMAGE_EXT, import_raster, is_scanned_pdf

    if suffix in IMAGE_EXT:
        return import_raster(path, page=page, px_per_m=px_per_m, scale=scale)
    if suffix == ".pdf":
        if px_per_m or is_scanned_pdf(path, page):
            return import_raster(path, page=page, px_per_m=px_per_m, scale=scale)
        from .pdf_importer import import_pdf

        return import_pdf(path, scale=scale, page_number=page)
    raise ValueError(f"Format de fichier non pris en charge : {suffix} (attendu : .dwg, .dxf, .pdf, ou image scannée "
                     ".png/.jpg/.tif)")


TITLE_HINT = re.compile(r"PLAN|NIVEAU|ETAGE|R\.?D\.?C|REZ|SOUS.?SOL|TERRASSE|TOITURE|FACADE|COUPE|MASSE|FONDATION",
                        re.IGNORECASE)


def _title_from_name(name: str) -> str:
    """« rdc.pdf » → « PLAN RDC » ; « Coupe A-A.dwg » → « COUPE A-A »."""
    stem = re.sub(r"_+", " ", Path(name).stem).strip().upper()
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return stem if TITLE_HINT.search(stem) and not re.match(r"^(R\.?D\.?C|ETAGE|NIVEAU|REZ|SOUS)", stem) \
        else f"PLAN {stem}"


def import_plans(paths, *, units: str | None = None, scale: int | None = None, page: int = 1,
                 px_per_m: float | None = None, gap: float = 20.0) -> Drawing:
    """Plusieurs fichiers (un par niveau, coupes, façades…) assemblés côte à côte comme les planches
    d'un même dessin : chaque fichier sans cadre reçoit un cadre et un titre tiré de son nom."""
    from ..geometry import Rect, Text
    from ..sheets import find_sheets

    out = Drawing(source=" + ".join(Path(p).name for p in paths))
    x_next = 0.0
    scan = None
    for p in paths:
        d = import_plan(p, units=units, scale=scale, page=page, px_per_m=px_per_m)
        scan = scan or getattr(d, "scan", None)
        xs = [v for s in d.segments for v in (s.x0, s.x1)] + [v for r in d.rects for v in (r.x0, r.x1)] + [t.x for t in d.texts]
        ys = [v for s in d.segments for v in (s.y0, s.y1)] + [v for r in d.rects for v in (r.y0, r.y1)] + [t.y for t in d.texts]
        if not xs:
            out.warnings.append(f"{Path(p).name} : aucun contenu lu.")
            continue
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        dx, dy = x_next - x0, -y0
        for s in d.segments:
            s.x0, s.x1, s.y0, s.y1 = s.x0 + dx, s.x1 + dx, s.y0 + dy, s.y1 + dy
        for r in d.rects:
            r.x0, r.x1, r.y0, r.y1 = r.x0 + dx, r.x1 + dx, r.y0 + dy, r.y1 + dy
        for t in d.texts:
            t.x, t.y = t.x + dx, t.y + dy
        for m in d.marks:
            m.x0, m.x1, m.y0, m.y1 = m.x0 + dx, m.x1 + dx, m.y0 + dy, m.y1 + dy
        w, h = x1 - x0, y1 - y0
        titled = [sh for sh in find_sheets(d) if not sh.title.startswith("Planche ")]
        if not titled:     # pas de cadre titré : on en ajoute un, avec le nom du fichier comme titre
            m = max(1.0, 0.04 * max(w, h))
            d.rects.append(Rect(x_next - m, -m, x_next + w + m, h + 2.5 * m, layer="CADRE_FICHIER"))
            d.texts.append(Text(x_next + w / 2, h + 1.2 * m, _title_from_name(Path(p).name), layer="CADRE_FICHIER"))
        out.rects += d.rects
        out.segments += d.segments
        out.texts += d.texts
        out.marks += d.marks
        out.warnings += [f"{Path(p).name} : {w_}" for w_ in d.warnings]
        x_next += w + gap
    if scan is not None:
        out.scan = scan  # type: ignore[attr-defined]
    return out
