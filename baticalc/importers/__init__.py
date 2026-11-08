"""Importeurs de plans : DWG/DXF (AutoCAD), PDF vectoriel, plans scannés (images, PDF image)."""
from __future__ import annotations

from pathlib import Path

from ..geometry import Drawing


def import_plan(path: str | Path, *, units: str | None = None, scale: int | None = None, page: int = 1,
                px_per_m: float | None = None) -> Drawing:
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
