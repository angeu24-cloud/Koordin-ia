"""Plans scannés (PNG, JPG, TIFF, PDF image) : murs, poteaux, textes et échelle.

1. Image en niveaux de gris, traits sombres et peu colorés (les fenêtres bleues, les hachures
   rouges et les axes colorés sont écartés).
2. Traits horizontaux et verticaux : suites de pixels sombres d'au moins ~0,5 m, épaisseur de
   trait 2 à 8 px ; les murs sont les traits qui ont un **parallèle** à 7–40 cm (double trait) ;
   un mur plein (trait épais) donne ses deux faces.
3. Poteaux : taches pleines, presque carrées, de 15 à 60 cm.
4. Textes : OCR (RapidOCR, hors ligne) sur l'image et sur l'image tournée (cotes verticales),
   avec correction des noms de pièces (« CUISNE » → « CUISINE »).
5. Échelle : chaînes de cotes. Deux cotes voisines d'une même chaîne (valeurs v1, v2 en cm) sont
   séparées de (v1 + v2)/2 × échelle ; la valeur la plus fréquente sur toutes les paires est retenue.
   À défaut : échelle donnée (px/m) ou échelle du plan (1/100) avec la résolution du scan.
"""
from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..geometry import Drawing, Rect, Segment, Text

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
VOCAB = ["CUISINE", "SEJOUR", "SALON", "CHAMBRE", "PRINCIPALE", "PARENTALE", "DEGAGEMENT", "TERRASSE", "ARRIERE",
         "AVANT", "BALCON", "W.C.", "WC", "DOUCHE", "SALLE", "BAIN", "EAU", "SDB", "S.E.", "BUREAU", "GARAGE", "MAGASIN",
         "HALL", "ENTREE", "ESCALIER", "PALIER", "CIRCULATION", "VESTIAIRE", "TOILETTES", "BUANDERIE", "CELLIER",
         "DRESSING", "PLACARD", "SALLE A MANGER", "LOCAL", "TECHNIQUE", "ASCENSEUR", "ACCUEIL", "SECRETARIAT", "ARCHIVES",
         "REUNION", "VERANDA", "VIDE", "TREMIE", "PARKING", "BOUTIQUE", "SANITAIRES", "LAVERIE", "OFFICE", "STUDIO"]


class RasterImportError(RuntimeError):
    pass


@dataclass
class ScanInfo:
    width: int
    height: int
    px_per_m: float | None = None
    scale_source: str = ""
    tokens: list[tuple[float, float, str, float, bool]] = field(default_factory=list)   # x, y, texte, conf, vertical
    walls_px: list[tuple[float, float, float, float]] = field(default_factory=list)


# ----------------------------------------------------------------------------- chargement
def load_image(path: str | Path, page: int = 1) -> tuple[np.ndarray, float | None]:
    """Image RGB (uint8) et résolution en pixels par mètre de papier (si connue)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import pymupdf

        doc = pymupdf.open(path)
        pg = doc[page - 1]
        infos = sorted(pg.get_image_info(xrefs=True), key=lambda i: -(i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]))
        if infos and infos[0]["xref"]:
            pix = pymupdf.Pixmap(doc, infos[0]["xref"])
            if pix.n - pix.alpha >= 4 or pix.alpha:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            w_pt = infos[0]["bbox"][2] - infos[0]["bbox"][0]
            dpm = pix.width / (w_pt / 72 * 0.0254) if w_pt > 0 else None
        else:
            pix = pg.get_pixmap(dpi=200)
            dpm = 200 / 0.0254
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 1:
            arr = np.repeat(arr, 3, axis=2)
        return np.ascontiguousarray(arr[:, :, :3]), dpm
    from PIL import Image

    im = Image.open(path)
    dpi = im.info.get("dpi", (None, None))[0]
    return np.asarray(im.convert("RGB")), (float(dpi) / 0.0254 if dpi and dpi > 30 else None)


def is_scanned_pdf(path: str | Path, page: int = 1) -> bool:
    """Page PDF occupée par une grande image et presque sans traits vectoriels."""
    import pymupdf

    doc = pymupdf.open(path)
    pg = doc[page - 1]
    area = pg.rect.width * pg.rect.height
    big = any((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) > 0.3 * area for i in pg.get_image_info())
    return big and len(pg.get_drawings()) < 400


# ----------------------------------------------------------------------------- traits
def dark_mask(rgb: np.ndarray) -> np.ndarray:
    g = rgb.mean(axis=2)
    sat = rgb.max(axis=2).astype(int) - rgb.min(axis=2)
    # seuil d'Otsu sur les niveaux de gris
    hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256).astype(float)
    p = hist / hist.sum()
    w = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        sb = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    thr = min(int(np.nanargmax(sb)), 150)
    reddish = rgb[:, :, 0].astype(int) - rgb[:, :, 1] > 50      # hachures, escaliers en rouge
    return (g < thr) & (sat < 80) & ~reddish


def window_mask(rgb: np.ndarray) -> np.ndarray:
    """Menuiseries dessinées en bleu / cyan (elles ferment les murs)."""
    r, g, b = (rgb[:, :, i].astype(int) for i in range(3))
    return (b - r > 45) & (b > 90)


def _runs(row: np.ndarray, min_len: int):
    a = np.concatenate([[0], row.astype(np.int8), [0]])
    d = np.diff(a)
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    keep = (e - s) >= min_len
    return s[keep], e[keep]


def _components(runs_by_row: dict[int, list[tuple[int, int]]]) -> list[tuple[int, int, int, int]]:
    """Regroupe des suites horizontales qui se touchent d'une ligne à l'autre → boîtes (x0, y0, x1, y1)."""
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    prev: list[tuple[int, int, tuple[int, int]]] = []
    prev_y = None
    for y in sorted(runs_by_row):
        cur = []
        for i, (s, e) in enumerate(runs_by_row[y]):
            k = (y, i)
            parent[k] = k
            if prev_y == y - 1:
                for ps, pe, pk in prev:
                    if ps < e and s < pe:
                        parent[find(k)] = find(pk)
            cur.append((s, e, k))
        prev, prev_y = cur, y
    boxes: dict[tuple[int, int], list[int]] = {}
    for y, rr in runs_by_row.items():
        for i, (s, e) in enumerate(rr):
            r = find((y, i))
            b = boxes.setdefault(r, [s, y, e, y + 1])
            b[0], b[1], b[2], b[3] = min(b[0], s), min(b[1], y), max(b[2], e), max(b[3], y + 1)
    return [tuple(b) for b in boxes.values()]


def line_boxes(mask: np.ndarray, min_len: int, max_thick: int) -> list[tuple[int, int, int, int]]:
    """Traits horizontaux : composantes de suites ≥ min_len, d'épaisseur ≤ max_thick."""
    runs: dict[int, list[tuple[int, int]]] = {}
    for y in range(mask.shape[0]):
        s, e = _runs(mask[y], min_len)
        if len(s):
            runs[y] = list(zip(s.tolist(), e.tolist()))
    return [b for b in _components(runs) if 1 <= b[3] - b[1] and b[2] - b[0] >= min_len]


def token_box(t) -> tuple[float, float, float, float]:
    x, y, _txt, _c, vert, w, h = t[:7]
    if vert:
        w, h = h, w
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def mask_text(mask: np.ndarray, tokens, pad: int = 2) -> np.ndarray:
    m = mask.copy()
    H, W = m.shape
    for t in tokens:
        x0, y0, x1, y1 = token_box(t)
        m[max(0, int(y0) - pad):min(H, int(y1) + pad + 1), max(0, int(x0) - pad):min(W, int(x1) + pad + 1)] = False
    return m


def _is_dimension(axis: int, a0: float, ay: float, a1: float, nums, px_per_m: float) -> bool:
    """Trait (le long de x pour axis 0) dont une extrémité touche un nombre aligné : ligne de cote."""
    for (nx, ny, nw, nh) in nums:
        along, perp, half = (nx, ny, nw / 2) if axis == 0 else (ny, nx, nh / 2)
        if abs(perp - ay) > max(0.6 * (nh if axis == 0 else nw), 4):
            continue
        if a1 - 3 <= along - half <= a1 + 0.35 * px_per_m or a0 - 0.35 * px_per_m <= along + half <= a0 + 3:
            return True
        if a0 < along < a1:     # nombre posé sur le trait
            return True
    return False


def wall_segments(mask: np.ndarray, px_per_m: float, tokens=()) -> tuple[list[tuple], list[tuple]]:
    """Faces de murs (en px) : traits ayant un parallèle à 7–40 cm, et traits épais (murs pleins)."""
    min_len = max(12, int(0.45 * px_per_m))
    tboxes = [token_box(t) for t in tokens]
    nums = {False: [], True: []}
    for t in tokens:
        if re.search(r"\d{2}", t[2]):
            x0, y0, x1, y1 = token_box(t)
            nums[bool(t[4])].append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0))
    out_h, out_v = [], []
    for axis, out in ((0, out_h), (1, out_v)):
        m = mask if axis == 0 else mask.T
        boxes = line_boxes(m, min_len, 10 ** 6)
        thin, thick = [], []
        # cotes d'un trait horizontal : textes horizontaux ; d'un trait vertical : textes verticaux
        nums_ax = nums[False] if axis == 0 else [(ny, nx, nh, nw) for nx, ny, nw, nh in nums[True]]
        tb_ax = tboxes if axis == 0 else [(b, a, d, c) for a, b, c, d in tboxes]
        for x0, y0, x1, y1 in boxes:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if any(a <= mx <= c and b <= my <= d and (x1 - x0) < 1.3 * (c - a) for a, b, c, d in tb_ax):
                continue      # trait de lettre ou souligné d'un texte
            if _is_dimension(0, x0, (y0 + y1) / 2, x1, nums_ax, px_per_m):
                continue
            t = y1 - y0
            if t >= 0.07 * px_per_m and t <= 0.45 * px_per_m:
                thick.append((x0, y0, x1, y1))
            elif t < 0.07 * px_per_m:
                thin.append((x0, (y0 + y1) / 2, x1))
        thin.sort(key=lambda b: b[1])
        lo, hi = 0.06 * px_per_m, 0.42 * px_per_m
        keep = set()
        for i, (a0, ay, a1) in enumerate(thin):
            for j in range(i + 1, len(thin)):
                b0, by, b1 = thin[j]
                if by - ay > hi:
                    break
                if by - ay < lo:
                    continue
                ov = min(a1, b1) - max(a0, b0)
                if ov > 0.5 * min(a1 - a0, b1 - b0):
                    keep.update((i, j))
        for i in keep:
            a0, ay, a1 = thin[i]
            out.append((a0, ay, a1, ay))
        for x0, y0, x1, y1 in thick:
            out.append((x0, y0, x1, y0))
            out.append((x0, y1, x1, y1))
        if axis == 1:
            out[:] = [(y, x0, y, x1) for (x0, y, x1, _) in out]
    return out_h, out_v


def _erode(mask: np.ndarray, k: int) -> np.ndarray:
    """Érosion par un carré k × k (image intégrale) : seules les zones pleines subsistent."""
    ii = np.pad(mask.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    H, W = mask.shape
    out = np.zeros_like(mask)
    s = ii[k:, k:] - ii[:-k, k:] - ii[k:, :-k] + ii[:-k, :-k]
    out[k // 2:k // 2 + s.shape[0], k // 2:k // 2 + s.shape[1]] = s == k * k
    return out


def column_boxes(mask: np.ndarray, px_per_m: float) -> list[tuple[int, int, int, int]]:
    """Taches pleines presque carrées de 15 à 60 cm (poteaux noircis), même traversées par des murs."""
    k = max(3, int(round(0.10 * px_per_m)))
    core = _erode(mask, k)
    runs: dict[int, list[tuple[int, int]]] = {}
    for y in range(core.shape[0]):
        a, b = _runs(core[y], 1)
        if len(a):
            runs[y] = list(zip(a.tolist(), b.tolist()))
    lo, hi = 0.13 * px_per_m, 0.65 * px_per_m
    out = []
    for x0, y0, x1, y1 in _components(runs):
        x0, y0, x1, y1 = x0 - k // 2, y0 - k // 2, x1 + k // 2, y1 + k // 2
        w, h = x1 - x0, y1 - y0
        if lo <= w <= hi and lo <= h <= hi and max(w, h) / min(w, h) < 1.8:
            out.append((max(0, x0), max(0, y0), x1, y1))
    return out


# ----------------------------------------------------------------------------- OCR
def ocr_tokens(rgb: np.ndarray, upscale: float | tuple = (2.0, 3.0)) -> list[tuple]:
    """(x, y, texte, confiance, vertical) en pixels de l'image d'origine."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return []
    import cv2

    ocr = RapidOCR()
    if isinstance(upscale, (tuple, list)):     # plusieurs agrandissements : les petits textes au plus fort
        merged: list = []
        for up in upscale:
            for t in ocr_tokens(rgb, float(up)):
                clash = [m for m in merged if abs(m[0] - t[0]) < 20 and abs(m[1] - t[1]) < 12 and m[4] == t[4]]
                if not clash:
                    merged.append(t)
                elif t[3] > max(m[3] for m in clash) + 0.05:
                    for m in clash:
                        merged.remove(m)
                    merged.append(t)
        return merged
    out = []
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    big = cv2.resize(img, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC) if upscale != 1 else img
    for rot in (False, True):
        src = cv2.rotate(big, cv2.ROTATE_90_CLOCKWISE) if rot else big
        res, _ = ocr(src)
        for box, txt, conf in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            cx, cy = sum(xs) / 4, sum(ys) / 4
            if rot:   # retour au repère de l'image : (x, y)_rot = (H − 1 − y, x)
                cx, cy = cy, big.shape[0] - 1 - cx
            w = (max(xs) - min(xs)) / upscale
            h = (max(ys) - min(ys)) / upscale
            out.append((cx / upscale, cy / upscale, str(txt), float(conf), rot, w, h))
    # doublons : un texte horizontal relu sur l'image tournée est ignoré
    hor = [t for t in out if not t[4]]
    keep = hor[:]
    for t in out:
        if t[4] and not any(abs(t[0] - h[0]) < 25 and abs(t[1] - h[1]) < 25 for h in hor):
            keep.append(t)
    return keep


NUM_RE = re.compile(r"\d{2,4}")


def _split_numbers(tok) -> list[tuple[float, float, int]]:
    """Nombres d'un texte de cote, avec leur position estimée le long du texte."""
    x, y, txt, conf, vert, w = tok[:6]
    s = txt.strip()
    parts = [(m.start(), m.end(), int(m.group())) for m in NUM_RE.finditer(s)]
    if not parts or not w:
        return []
    out = []
    n = max(1, len(s))
    for a, b, v in parts:
        if b - a > 4:          # chiffres collés sans séparateur : ambigu
            continue
        f = ((a + b) / 2) / n - 0.5
        if vert:
            out.append((x, y - f * w, v))   # texte vertical : le long de y (lu de bas en haut)
        else:
            out.append((x + f * w, y, v))
    return out


def scale_from_dimensions(tokens, min_pairs: int = 3) -> float | None:
    """px par mètre d'après les chaînes de cotes (valeurs en cm)."""
    cands = []
    for vert in (False, True):
        pts = []
        for t in tokens:
            if t[4] == vert and t[3] > 0.5:
                pts += _split_numbers(t)
        key = (lambda p: p[0]) if vert else (lambda p: p[1])
        along = (lambda p: p[1]) if vert else (lambda p: p[0])
        pts.sort(key=lambda p: (round(key(p) / 6), along(p)))
        rows: list[list] = []
        for p in pts:
            if rows and abs(key(rows[-1][-1]) - key(p)) < 6:
                rows[-1].append(p)
            else:
                rows.append([p])
        for row in rows:
            row.sort(key=along)
            for a, b in zip(row, row[1:]):
                d = abs(along(b) - along(a))
                v = (a[2] + b[2]) / 2
                if 5 <= v <= 1500 and d > 8:
                    cands.append(d / v * 100)
    if len(cands) < min_pairs:
        return None
    c = np.array(cands)
    # mode robuste : histogramme logarithmique, puis médiane autour du pic
    bins = np.exp(np.arange(np.log(5), np.log(2000), 0.03))
    h, edges = np.histogram(c, bins=bins)
    k = int(np.argmax(np.convolve(h, [1, 2, 1], "same")))
    lo, hi = edges[max(0, k - 2)], edges[min(len(edges) - 1, k + 3)]
    sel = c[(c >= lo) & (c <= hi)]
    if len(sel) < max(3, 0.15 * len(c)):
        return None
    return float(np.median(sel))


_WORDS = sorted({w for v in VOCAB for w in v.replace(".", "").split()}, key=len, reverse=True)


def _match(word: str) -> str | None:
    m = difflib.get_close_matches(word, _WORDS, n=1, cutoff=0.72)
    return m[0] if m else None


def correct_label(txt: str) -> str:
    """Corrige les noms de pièces lus par l'OCR (mots du vocabulaire), garde le reste."""
    words = re.findall(r"[A-Za-zÀ-ÿ.]+|\S", txt.upper())
    out = []
    for w in words:
        base = w.strip(".")
        if len(base) >= 4 and base.isalpha():
            m = _match(base)
            if len(base) >= 9:   # mots collés : « TERRASSEAVANT » → « TERRASSE AVANT »
                best = None
                for i in range(3, len(base) - 2):
                    a, b = _match(base[:i]), _match(base[i:])
                    if a and b:
                        sc = difflib.SequenceMatcher(None, base, a + b).ratio()
                        if not best or sc > best[0]:
                            best = (sc, f"{a} {b}")
                if best and (not m or best[0] > difflib.SequenceMatcher(None, base, m).ratio()):
                    m = best[1]
            out.append(m if m else w)
        else:
            out.append(w)
    s = " ".join(out)
    s = re.sub(r"\b(CHAMBRE)\s*(\d)", r"\1 \2", s)
    return s


# ----------------------------------------------------------------------------- import
def import_raster(path: str | Path, page: int = 1, px_per_m: float | None = None, scale: int | None = None) -> Drawing:
    rgb, dpm = load_image(path, page)
    H, W = rgb.shape[:2]
    out = Drawing(source=f"{path} (scan {W}×{H} px)")
    info = ScanInfo(W, H)
    tokens = ocr_tokens(rgb)
    info.tokens = [t[:5] for t in tokens]
    if px_per_m:
        info.px_per_m, info.scale_source = float(px_per_m), "donnée"
    else:
        s = scale_from_dimensions(tokens)
        if s:
            info.px_per_m, info.scale_source = s, "chaînes de cotes"
        elif scale and dpm:
            info.px_per_m, info.scale_source = dpm / scale, f"1/{scale} et résolution du scan"
    if not info.px_per_m:
        raise RasterImportError(
            "Échelle du scan introuvable : aucune chaîne de cotes lisible. Indiquez l'échelle en pixels par mètre "
            "(lecture → echelle_px_m) ou l'échelle du plan (--echelle 100) si le scan est à 100 % du papier."
            + ("" if tokens else " (OCR indisponible : installez rapidocr-onnxruntime)"))
    k = 1.0 / info.px_per_m

    def P(x, y):
        return x * k, (H - y) * k

    mask = dark_mask(rgb)
    hs, vs = wall_segments(mask, info.px_per_m, tokens)
    # fenêtres (bleu) : traits allongés posés dans l'épaisseur des murs
    win = window_mask(rgb)
    if win.mean() > 1e-4:
        for axis in (0, 1):
            m = win if axis == 0 else win.T
            for x0, y0, x1, y1 in line_boxes(m, max(8, int(0.3 * info.px_per_m)), 10 ** 6):
                if y1 - y0 <= 0.3 * info.px_per_m:
                    yc = (y0 + y1) / 2
                    seg = (x0, yc, x1, yc) if axis == 0 else (yc, x0, yc, x1)
                    (hs if axis == 0 else vs).append(seg)
    for x0, y0, x1, y1 in hs + vs:
        a, b = P(x0, y0), P(x1, y1)
        out.segments.append(Segment(a[0], a[1], b[0], b[1], layer="MURS"))
        info.walls_px.append((x0, y0, x1, y1))
    for x0, y0, x1, y1 in column_boxes(mask, info.px_per_m):
        a, b = P(x0, y1), P(x1, y0)
        out.rects.append(Rect(a[0], a[1], b[0], b[1], layer="POTEAUX", filled=True))
    labels = []
    for x, y, txt, conf, vert, *_r in tokens:
        if conf < 0.5:
            continue
        if re.search(r"[A-Za-z]{3,}", txt) and not vert:
            labels.append([x, y, correct_label(txt)])
            continue
        a = P(x, y)
        m_ = re.match(r"^\s*(\d{1,3})[.,](\d{1,2})\s*m\S?\s*$", txt)   # surface sans « ² » : « 33.05m »
        if m_:
            txt = f"{m_.group(1)}.{m_.group(2)} m²"
        out.texts.append(Text(a[0], a[1], txt, layer="TEXTES_SCAN"))
    # noms de pièces écrits sur deux lignes (« CHAMBRE » / « PRINCIPALE »)
    labels.sort(key=lambda t: t[1])
    used = set()
    for i, a_ in enumerate(labels):
        if i in used:
            continue
        name = a_[2]
        for j in range(i + 1, len(labels)):
            b_ = labels[j]
            if j not in used and 0 < b_[1] - a_[1] < 0.45 * info.px_per_m and abs(b_[0] - a_[0]) < 0.8 * info.px_per_m:
                name += " " + b_[2]
                used.add(j)
                break
        p_ = P(a_[0], a_[1])
        out.texts.append(Text(p_[0], p_[1], name, layer="TEXTES_SCAN"))
    out.warnings.append(f"Plan scanné : échelle {info.px_per_m:.2f} px/m ({info.scale_source}), {len(hs) + len(vs)} faces "
                        f"de murs, {len(out.rects)} poteaux noircis, {len(out.texts)} textes lus. À contrôler sur le plan "
                        "de contrôle.")
    out.scan = info  # type: ignore[attr-defined]
    return out
