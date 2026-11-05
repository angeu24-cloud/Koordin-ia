"""Génère un plan d'exemple (DXF et PDF) pour tester la chaîne complète."""
from __future__ import annotations

from pathlib import Path

import ezdxf


def sample_grid(spans_x=(4.0, 4.5, 4.0), spans_y=(5.0, 4.0), col=0.30) -> tuple[list[float], list[float], float]:
    xs = [0.0]
    for s in spans_x:
        xs.append(xs[-1] + s)
    ys = [0.0]
    for s in spans_y:
        ys.append(ys[-1] + s)
    return xs, ys, col


def write_sample_dxf(path: str | Path, *, units_mm: bool = True, with_layer: bool = True) -> Path:
    """Plan d'architecte simplifié : murs, poteaux 30×30 hachurés, texte, cartouche."""
    xs, ys, a = sample_grid()
    k = 1000.0 if units_mm else 1.0
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4 if units_mm else 6
    msp = doc.modelspace()
    layer = "POTEAUX" if with_layer else "0"
    doc.layers.add("MURS")
    if with_layer:
        doc.layers.add("POTEAUX")
    # Murs extérieurs (épaisseur 20 cm) — grands rectangles, ne doivent pas être pris pour des poteaux
    W, H = xs[-1], ys[-1]
    for off in (-0.25, 0.05):
        msp.add_lwpolyline([(-0.25 * k if off < 0 else 0.05 * k, -0.25 * k if off < 0 else 0.05 * k),
                            ((W + (0.25 if off < 0 else -0.05)) * k, -0.25 * k if off < 0 else 0.05 * k),
                            ((W + (0.25 if off < 0 else -0.05)) * k, (H + (0.25 if off < 0 else -0.05)) * k),
                            (-0.25 * k if off < 0 else 0.05 * k, (H + (0.25 if off < 0 else -0.05)) * k)],
                           close=True, dxfattribs={"layer": "MURS"})
    # Une table (mobilier) : petit rectangle sans hachure → ne doit pas perturber
    msp.add_lwpolyline([(1.5 * k, 1.5 * k), (2.3 * k, 1.5 * k), (2.3 * k, 2.1 * k), (1.5 * k, 2.1 * k)],
                       close=True, dxfattribs={"layer": "MOBILIER"})
    for x in xs:
        for y in ys:
            pts = [((x - a / 2) * k, (y - a / 2) * k), ((x + a / 2) * k, (y - a / 2) * k),
                   ((x + a / 2) * k, (y + a / 2) * k), ((x - a / 2) * k, (y + a / 2) * k)]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
            hatch = msp.add_hatch(color=7, dxfattribs={"layer": layer})
            hatch.paths.add_polyline_path(pts, is_closed=True)
    msp.add_text("SEJOUR", dxfattribs={"layer": "TEXTE", "height": 0.2 * k, "insert": (2 * k, 3 * k)})
    path = Path(path)
    doc.saveas(path)
    return path


def write_sample_pdf(path: str | Path, scale: int = 100) -> Path:
    """Même plan, exporté en PDF vectoriel au 1/scale avec poteaux remplis en noir."""
    import pymupdf as fitz

    xs, ys, a = sample_grid()
    mm_to_pt = 72 / 25.4
    k = 1000 / scale * mm_to_pt  # m réels -> points
    margin = 60
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 paysage
    Hp = page.rect.height

    def R(x0, y0, x1, y1):
        return fitz.Rect(margin + x0 * k, Hp - margin - y1 * k, margin + x1 * k, Hp - margin - y0 * k)

    W, H = xs[-1], ys[-1]
    page.draw_rect(R(-0.25, -0.25, W + 0.25, H + 0.25), color=(0, 0, 0), width=0.5)
    page.draw_rect(R(0.05, 0.05, W - 0.05, H - 0.05), color=(0, 0, 0), width=0.5)
    page.draw_rect(R(1.5, 1.5, 2.3, 2.1), color=(0.5, 0.5, 0.5), width=0.3)  # mobilier
    for x in xs:
        for y in ys:
            page.draw_rect(R(x - a / 2, y - a / 2, x + a / 2, y + a / 2), color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((600, 560), f"PLAN RDC - Ech : 1/{scale}", fontsize=9)
    path = Path(path)
    doc.save(path)
    return path
