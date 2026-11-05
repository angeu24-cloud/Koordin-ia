"""Primitives géométriques neutres produites par les importeurs (DWG/DXF, PDF).

Toutes les coordonnées sont en mètres, axe Y vers le haut.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float
    layer: str = ""
    filled: bool = False

    def __post_init__(self) -> None:
        self.x0, self.y0, self.x1, self.y1 = float(self.x0), float(self.y0), float(self.x1), float(self.y1)
        if self.x0 > self.x1:
            self.x0, self.x1 = self.x1, self.x0
        if self.y0 > self.y1:
            self.y0, self.y1 = self.y1, self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float
    layer: str = ""

    def __post_init__(self) -> None:
        self.x0, self.y0, self.x1, self.y1 = float(self.x0), float(self.y0), float(self.x1), float(self.y1)


@dataclass
class Text:
    x: float
    y: float
    text: str
    layer: str = ""


@dataclass
class Drawing:
    """Contenu géométrique d'un plan, après import."""
    rects: list[Rect] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    source: str = ""
    warnings: list[str] = field(default_factory=list)


def rect_from_points(pts: list[tuple[float, float]], tol: float = 1e-3) -> tuple[float, float, float, float] | None:
    """Renvoie (x0, y0, x1, y1) si les points forment un rectangle aligné sur les axes."""
    uniq: list[tuple[float, float]] = []
    for p in pts:
        if not any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in uniq):
            uniq.append(p)
    if len(uniq) != 4:
        return None
    x0, x1 = min(p[0] for p in uniq), max(p[0] for p in uniq)
    y0, y1 = min(p[1] for p in uniq), max(p[1] for p in uniq)
    if x1 - x0 <= tol or y1 - y0 <= tol:
        return None
    corners = set()
    for px, py in uniq:
        cx = 0 if abs(px - x0) <= tol else (1 if abs(px - x1) <= tol else None)
        cy = 0 if abs(py - y0) <= tol else (1 if abs(py - y1) <= tol else None)
        if cx is None or cy is None:
            return None
        corners.add((cx, cy))
    if len(corners) != 4:
        return None
    return x0, y0, x1, y1
