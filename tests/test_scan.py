"""Plans scannés : murs, poteaux, pièces, échelle par les chaînes de cotes, correction des libellés."""
import pytest
from PIL import Image, ImageDraw, ImageFont

from baticalc.importers import import_plan
from baticalc.importers.raster_importer import correct_label, scale_from_dimensions
from baticalc.recognition import build_model

PX = 50.0    # px / m du scan synthétique
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _wall(d, x0, y0, x1, y1, t=0.2):
    """Mur en double trait (épaisseur t, traits de 3 px)."""
    if y0 == y1:
        for yy in (y0 - t / 2, y0 + t / 2):
            d.line([x0 * PX, yy * PX, x1 * PX, yy * PX], fill=0, width=3)
    else:
        for xx in (x0 - t / 2, x0 + t / 2):
            d.line([xx * PX, y0 * PX, xx * PX, y1 * PX], fill=0, width=3)


def write_scan(path, chain=True):
    im = Image.new("RGB", (int(24 * PX), int(17 * PX)), "white")
    d = ImageDraw.Draw(im)
    o = 2.0
    # enveloppe 20 × 12 m, avec une fenêtre bleue dans la façade sud
    _wall(d, o, o, o + 20, o)
    _wall(d, o, o + 12, o + 6, o + 12)
    _wall(d, o + 8, o + 12, o + 20, o + 12)
    d.line([(o + 6) * PX, (o + 12) * PX, (o + 8) * PX, (o + 12) * PX], fill=(40, 90, 230), width=5)
    _wall(d, o, o, o, o + 12)
    _wall(d, o + 20, o, o + 20, o + 12)
    # refend à x = 10 m avec une porte de 0,9 m
    _wall(d, o + 10, o, o + 10, o + 5)
    _wall(d, o + 10, o + 5.9, o + 10, o + 12)
    # WC de 2 × 2 m dans l'angle nord-est (porte 0,8 m)
    _wall(d, o + 18, o, o + 18, o + 1.2)
    _wall(d, o + 18, o + 2, o + 20, o + 2)
    # poteaux noircis 25 × 25 aux angles et au milieu
    for x, y in ((o, o), (o + 20, o), (o, o + 12), (o + 20, o + 12), (o + 10, o), (o + 10, o + 12)):
        d.rectangle([(x - .125) * PX, (y - .125) * PX, (x + .125) * PX, (y + .125) * PX], fill=0)
    if chain:   # chaîne de cotes au-dessus du bâtiment (cm)
        f = ImageFont.truetype(FONT, 22)
        y = (o - 1.2) * PX
        d.line([o * PX, y, (o + 20) * PX, y], fill=0, width=1)
        x = o
        for v in (500, 500, 600, 200, 200):
            d.text(((x + v / 200) * PX, y - 14), str(v), fill=0, font=f, anchor="mm")
            d.line([x * PX, y - 8, x * PX, y + 8], fill=0, width=1)
            x += v / 100
        f2 = ImageFont.truetype(FONT, 26)
        d.text(((o + 4) * PX, (o + 6) * PX), "SEJOUR", fill=0, font=f2, anchor="mm")
        d.text(((o + 15) * PX, (o + 7) * PX), "CHAMBRE", fill=0, font=f2, anchor="mm")
    im.save(path)
    return path


def test_walls_columns_and_rooms_with_given_scale(tmp_path):
    d = import_plan(write_scan(tmp_path / "plan.png", chain=False), px_per_m=PX)
    assert d.scan.px_per_m == PX
    xs = [v for s in d.segments for v in (s.x0, s.x1)]
    assert max(xs) - min(xs) == pytest.approx(20.2, abs=0.3)
    assert len([r for r in d.rects if r.layer == "POTEAUX"]) == 6
    bld = build_model(d)
    assert len(bld.columns) == 6
    assert SlabArea(bld) == pytest.approx(240, rel=0.12)
    wet = [z for z in bld.zones if z["name"].startswith("SALLE D'EAU")]
    assert len(wet) == 1 and wet[0]["area"] == pytest.approx(3.6, rel=0.35)
    assert bld.fixtures and {f["type"] for f in bld.fixtures} >= {"wc"}


def SlabArea(bld):
    from baticalc.slab import SlabMask

    return SlabMask.from_dict(bld.slab).area


def test_scale_from_dimension_chain_tokens():
    # (x, y, texte, confiance, vertical, largeur, hauteur) : 50 px/m, chaîne 500 | 300 | 420 | 120 cm
    toks, x = [], 100.0
    for v in (500, 300, 420, 120, 250):
        toks.append((x + v / 200 * 50, 40, str(v), 0.9, False, 30, 14))
        x += v / 100 * 50
    assert scale_from_dimensions(toks, min_pairs=3) == pytest.approx(50, rel=0.02)
    assert scale_from_dimensions(toks[:2], min_pairs=3) is None


def test_label_correction():
    assert correct_label("CUISNE") == "CUISINE"
    assert correct_label("TERRASSEAVANT") == "TERRASSE AVANT"
    assert correct_label("CHAMBRE2") == "CHAMBRE 2"
    assert correct_label("DEGAGEYONT") == "DEGAGEMENT"


def test_ocr_scale_and_labels(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    d = import_plan(write_scan(tmp_path / "plan.png"))
    assert d.scan.scale_source == "chaînes de cotes"
    assert d.scan.px_per_m == pytest.approx(PX, rel=0.05)
    names = " ".join(t.text for t in d.texts)
    assert "SEJOUR" in names and "CHAMBRE" in names
