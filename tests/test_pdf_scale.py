"""PDF vectoriel sans échelle écrite : échelle déduite des chaînes de cotes (cm ou m)."""
import pymupdf
import pytest

from baticalc.importers import import_plan
from baticalc.importers.pdf_importer import scale_from_dimension_texts


def write_pdf(path, scale, metres=False, vertical=True):
    k = 1000 / scale * 72 / 25.4      # m réels → points
    doc = pymupdf.open()
    pg = doc.new_page(width=1190, height=842)
    x0, y0 = 80, 700
    # bâtiment 14 × 9 m, murs doubles, poteaux noirs
    for d in (0, 0.2 * k):
        pg.draw_rect(pymupdf.Rect(x0 + d, y0 - 9 * k + d, x0 + 14 * k - d, y0 - d), color=(0, 0, 0), width=.5)
    for x in (0, 4.5, 9.5, 14):
        for y in (0, 4.5, 9):
            pg.draw_rect(pymupdf.Rect(x0 + x * k - 3, y0 - y * k - 3, x0 + x * k + 3, y0 - y * k + 3),
                         color=(0, 0, 0), fill=(0, 0, 0))
    # chaîne de cotes horizontale au-dessus
    yc, x = y0 - 9 * k - 20, 0.0
    pg.draw_line((x0, yc), (x0 + 14 * k, yc), color=(0, 0, 0), width=.3)
    for v in (450, 500, 450, 0):
        if v:
            txt = f"{v / 100:.2f}".replace(".", ",") if metres else str(v)
            pg.insert_text((x0 + (x + v / 200) * k - 8, yc - 3), txt, fontsize=7)
            x += v / 100
    if vertical:   # chaîne verticale à gauche, texte tourné
        xc, y = x0 - 20, 0.0
        for v in (450, 450):
            txt = f"{v / 100:.2f}".replace(".", ",") if metres else str(v)
            pg.insert_text((xc - 3, y0 - (y + v / 200) * k + 8), txt, fontsize=7, rotate=90)
            y += v / 100
    doc.save(path)
    return path


@pytest.mark.parametrize("scale,metres", [(50, False), (100, False), (100, True)])
def test_scale_from_dimension_chains(tmp_path, scale, metres):
    p = write_pdf(tmp_path / "plan.pdf", scale, metres)
    assert scale_from_dimension_texts(pymupdf.open(p)[0]) == scale
    d = import_plan(p)
    assert any("déduite des cotes" in w for w in d.warnings)
    xs = [v for r in d.rects for v in (r.x0, r.x1)]
    assert max(xs) - min(xs) == pytest.approx(14.2, abs=0.3)


def test_no_scale_message(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0))
    p = tmp_path / "vide.pdf"
    doc.save(p)
    with pytest.raises(RuntimeError, match="Échelle d'un PDF"):
        import_plan(p)
