"""Import des plans PDF vectoriels (exports AutoCAD, ArchiCAD, Revit…).

Les PDF scannés (images) ne contiennent pas de géométrie exploitable : ils sont
refusés avec un message explicite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from ..geometry import Drawing, Rect, Segment, Text, rect_from_points

PT_TO_MM = 25.4 / 72.0
_SCALE_RE = re.compile(r"(?:ech(?:elle)?|éch(?:elle)?|scale)?\s*[:.]?\s*1\s*[/:]\s*(\d{2,4})", re.IGNORECASE)


class PdfImportError(RuntimeError):
    pass


STANDARD_SCALES = (20, 25, 50, 75, 100, 125, 150, 200, 250, 500)


def scale_from_dimension_texts(page) -> float | None:
    """Échelle du plan (1/N) d'après les chaînes de cotes : textes de cotes et positions exactes du PDF."""
    from .raster_importer import scale_from_dimensions

    tokens = []
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            dx, dy = line["dir"]
            vert = abs(dy) > 0.9
            if not vert and abs(dx) < 0.9:
                continue
            for sp in line["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                w, h = x1 - x0, y1 - y0
                tokens.append(((x0 + x1) / 2, (y0 + y1) / 2, t, 1.0, vert, h if vert else w, w if vert else h))
    pts_per_m = scale_from_dimensions(tokens)
    if not pts_per_m:
        return None
    n = 1000.0 / (PT_TO_MM * pts_per_m)
    std = min(STANDARD_SCALES, key=lambda v: abs(v - n) / v)
    return float(std) if abs(std - n) / std < 0.04 else round(n, 1)


def detect_scale(text: str) -> int | None:
    """Cherche une échelle du type « Ech : 1/100 » ou « 1:50 » dans le cartouche."""
    candidates = [int(m.group(1)) for m in _SCALE_RE.finditer(text)]
    candidates = [c for c in candidates if c in (20, 25, 50, 75, 100, 125, 150, 200, 250, 500)]
    if not candidates:
        return None
    return max(set(candidates), key=candidates.count)


def import_pdf(path: str | Path, scale: int | None = None, page_number: int = 1) -> Drawing:
    doc = fitz.open(path)
    if page_number < 1 or page_number > doc.page_count:
        raise PdfImportError(f"Page {page_number} inexistante (le PDF contient {doc.page_count} page(s)).")
    page = doc[page_number - 1]
    out = Drawing(source=f"{path} (page {page_number})")

    page_text = page.get_text()
    if scale is None:
        scale = detect_scale(page_text)
        if scale is not None:
            out.warnings.append(f"Échelle détectée dans le cartouche : 1/{scale} (à vérifier).")
        else:
            scale = scale_from_dimension_texts(page)
            if scale is None:
                raise PdfImportError(
                    "Échelle du plan introuvable dans le PDF (ni « Éch. 1/100 » écrit, ni chaîne de cotes lisible). "
                    "Indiquez-la dans « Plan & niveaux › Échelle d'un PDF » (100 pour 1/100), ou --echelle 100."
                )
            out.warnings.append(f"Échelle déduite des cotes : 1/{scale:g} (à vérifier).")

    k = PT_TO_MM * scale / 1000.0  # points PDF -> mètres réels
    H = page.rect.height

    def P(p) -> tuple[float, float]:
        return (p.x * k, (H - p.y) * k)

    drawings = page.get_drawings()
    if not drawings:
        if page.get_images():
            raise PdfImportError(
                "Ce PDF semble scanné (image sans traits vectoriels) : la lecture automatique n'est pas possible.\n"
                "Demandez à l'architecte le DWG ou un PDF exporté directement depuis AutoCAD/Revit."
            )
        raise PdfImportError("Aucun trait vectoriel trouvé dans cette page.")

    for d in drawings:
        filled = d.get("fill") is not None
        layer = (d.get("layer") or "").upper()
        line_pts: list[tuple[float, float]] = []
        for item in d["items"]:
            op = item[0]
            if op == "re":
                r = item[1]
                a, b = P(fitz.Point(r.x0, r.y1)), P(fitz.Point(r.x1, r.y0))
                out.rects.append(Rect(a[0], a[1], b[0], b[1], layer=layer, filled=filled))
            elif op == "qu":
                q = item[1]
                rr = rect_from_points([P(q.ul), P(q.ur), P(q.ll), P(q.lr)], tol=0.005)
                if rr:
                    out.rects.append(Rect(*rr, layer=layer, filled=filled))
            elif op == "l":
                a, b = P(item[1]), P(item[2])
                line_pts += [a, b]
                out.segments.append(Segment(a[0], a[1], b[0], b[1], layer))
        # Rectangle dessiné avec 4 traits dans un même chemin
        if line_pts and len(d["items"]) in (3, 4):
            rr = rect_from_points(line_pts, tol=0.005)
            if rr:
                n = len(d["items"])
                del out.segments[-n:]
                out.rects.append(Rect(*rr, layer=layer, filled=filled))

    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                x, y = span["origin"]
                out.texts.append(Text(x * k, (H - y) * k, span["text"]))
    return out
