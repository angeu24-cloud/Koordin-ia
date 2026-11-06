"""Icône Windows (baticalc.ico) dessinée d'après baticalc/web/static/icone.svg."""
from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    k = size / 64
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=12 * k, fill="#1f4e79")
    w = max(1, round(4 * k))
    for x, y0 in ((14, 22), (32, 14), (50, 22)):
        d.line([(x * k, y0 * k), (x * k, 50 * k)], fill="white", width=w)
    for y in (22, 36):
        d.line([(10 * k, y * k), (54 * k, y * k)], fill="white", width=w)
    d.line([(8 * k, 52 * k), (56 * k, 52 * k)], fill="#f2a900", width=max(1, round(5 * k)))
    return im


if __name__ == "__main__":
    out = Path(__file__).with_name("baticalc.ico")
    draw(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
