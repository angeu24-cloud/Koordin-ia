"""Importeurs de plans : DWG/DXF (AutoCAD) et PDF vectoriel."""
from __future__ import annotations

from pathlib import Path

from ..geometry import Drawing


def import_plan(path: str | Path, *, units: str | None = None, scale: int | None = None, page: int = 1) -> Drawing:
    suffix = Path(path).suffix.lower()
    try:
        with open(path, "rb") as f:
            magic = f.read(6)
    except OSError:
        magic = b""
    if suffix in (".dwg", ".dxf") or magic.startswith(b"AC10"):
        from .dxf_importer import import_dxf

        return import_dxf(path, units=units)
    if suffix == ".pdf":
        from .pdf_importer import import_pdf

        return import_pdf(path, scale=scale, page_number=page)
    raise ValueError(f"Format de fichier non pris en charge : {suffix} (attendu : .dwg, .dxf, .pdf)")
