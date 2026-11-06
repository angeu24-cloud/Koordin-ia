"""BatiCalc — dimensionnement de bâtiments en béton armé à partir de plans DWG/DXF/PDF.

Règlements : BAEL 91 mod. 99, Eurocode 2 (CM66 / Eurocode 3 prévus).
"""
__version__ = "0.1.0"

OLD_NAME = "koordinia"   # ancien nom de l'application (Koordin-IA) : fichiers et variables encore acceptés


def env(name: str, default: str | None = None) -> str | None:
    """Variable d'environnement BATICALC_<name>, ou l'ancienne KOORDINIA_<name>."""
    import os

    return os.environ.get(f"BATICALC_{name}", os.environ.get(f"KOORDINIA_{name}", default))


def data_dir(path: str = "donnees_baticalc") -> str:
    """Dossier de données de l'application web ; reprend l'ancien dossier s'il existe seul."""
    from pathlib import Path

    p = Path(path)
    old = p.with_name(p.name.replace("baticalc", OLD_NAME))
    return str(old) if not p.exists() and old != p and old.exists() else str(p)
