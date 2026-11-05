"""Règlements de calcul disponibles.

Béton armé : BAEL 91 mod. 99, Eurocode 2.
Acier (CM66, Eurocode 3) : prévu en phase 2.
"""
from __future__ import annotations

from .bael import BAEL
from .ec2 import EC2


def get_code(name: str, *, fc: float | None = None, fy: float | None = None, cover: float = 0.03):
    name = name.lower()
    if name in ("bael", "bael91", "bael99"):
        return BAEL(fc28=fc or 25.0, fe=fy or 400.0, cover=cover)
    if name in ("ec2", "eurocode", "eurocode2"):
        return EC2(fck=fc or 25.0, fyk=fy or 500.0, cover=cover)
    if name in ("cm66", "ec3"):
        raise NotImplementedError(
            f"Le règlement {name.upper()} (charpente métallique) est prévu en phase 2 ; "
            "utilisez --norme bael ou --norme ec2 pour le béton armé."
        )
    raise ValueError(f"Règlement inconnu : {name}")
