"""Koordin Paie : gestion des contrats de travail et de la paie (Côte d'Ivoire)."""
__version__ = "0.1.0"


def creer_app(*args, **kwargs):
    from .app import creer_app as _creer

    return _creer(*args, **kwargs)
