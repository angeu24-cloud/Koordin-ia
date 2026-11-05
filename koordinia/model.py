"""Modèle structurel du bâtiment.

Unités internes : mètres (m), kilonewtons (kN), mégapascals (MPa).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Column:
    id: str
    x: float          # centre (m)
    y: float
    b: float          # dimension selon X (m)
    h: float          # dimension selon Y (m)
    grid_i: int = -1  # indice de file selon X
    grid_j: int = -1  # indice de file selon Y


@dataclass
class Beam:
    id: str
    start: str        # id du poteau de départ
    end: str          # id du poteau d'arrivée
    b: float          # largeur (m)
    h: float          # hauteur totale (m)
    direction: str    # "X" ou "Y"

    def length(self, cols: dict[str, Column]) -> float:
        c1, c2 = cols[self.start], cols[self.end]
        return ((c1.x - c2.x) ** 2 + (c1.y - c2.y) ** 2) ** 0.5


@dataclass
class Panel:
    """Panneau de plancher délimité par 4 poutres."""
    id: str
    beams: list[str]  # [bas (X), haut (X), gauche (Y), droite (Y)]
    lx: float         # dimension selon X (m)
    ly: float         # dimension selon Y (m)
    corners: list[str]  # ids des 4 poteaux d'angle


@dataclass
class LoadSettings:
    floor_type: str = "corps_creux"       # "corps_creux" (porteur 1 sens) ou "dalle_pleine" (2 sens)
    g_floor: float = 2.85                 # poids propre plancher (kN/m²) — 16+4 par défaut
    g_finishes: float = 2.00              # revêtements + cloisons (kN/m²)
    q_floor: float = 1.50                 # exploitation étage courant (kN/m²) — habitation
    g_roof_extra: float = 1.50            # forme de pente + étanchéité + protection (kN/m²)
    q_roof: float = 1.00                  # terrasse inaccessible (kN/m²)
    facade_load: float = 0.0              # charge linéique de maçonnerie sur poutres de rive (kN/m)
    degression: bool = True               # loi de dégression des charges d'exploitation
    continuity: bool = True               # majoration 10 % / 15 % des poteaux voisins de rive
    transfer_max_span: float = 12.0       # portée maximale d'une poutre de transfert automatique (m)


@dataclass
class Building:
    columns: list[Column] = field(default_factory=list)
    beams: list[Beam] = field(default_factory=list)
    panels: list[Panel] = field(default_factory=list)
    n_levels: int = 1                     # nombre de niveaux (planchers) au-dessus des fondations
    floor_height: float = 3.0             # hauteur d'étage (m)
    grid_x: list[float] = field(default_factory=list)
    grid_y: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""
    slab: dict | None = None              # contour du plancher (grille, voir slab.SlabMask)
    origin: list[float] = field(default_factory=lambda: [0.0, 0.0])  # origine dans le dessin (m)
    axis_x: list[str] = field(default_factory=list)   # repères des files selon X (lus sur le plan)
    axis_y: list[str] = field(default_factory=list)
    walls: list[list[float]] = field(default_factory=list)  # murs [x0, y0, x1, y1, épaisseur]
    zones: list[dict] = field(default_factory=list)          # locaux (voir zones.Zone), sur la grille de `slab`
    footprint: dict | None = None          # emprise propre du niveau (avant remplacement par le plancher haut)

    # ------------------------------------------------------------------ helpers
    def column_map(self) -> dict[str, Column]:
        return {c.id: c for c in self.columns}

    def beam_map(self) -> dict[str, Beam]:
        return {b.id: b for b in self.beams}

    # ------------------------------------------------------------- sérialisation
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Building":
        return cls(
            columns=[Column(**c) for c in d.get("columns", [])],
            beams=[Beam(**b) for b in d.get("beams", [])],
            panels=[Panel(**p) for p in d.get("panels", [])],
            n_levels=d.get("n_levels", 1),
            floor_height=d.get("floor_height", 3.0),
            grid_x=d.get("grid_x", []),
            grid_y=d.get("grid_y", []),
            warnings=d.get("warnings", []),
            source=d.get("source", ""),
            slab=d.get("slab"),
            origin=d.get("origin", [0.0, 0.0]),
            axis_x=d.get("axis_x", []),
            axis_y=d.get("axis_y", []),
            walls=d.get("walls", []),
            zones=d.get("zones", []),
            footprint=d.get("footprint"),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Building":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
