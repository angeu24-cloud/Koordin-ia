"""Niveaux du bâtiment : cotes lues sur les coupes et façades, affectation des
planches aux niveaux, calage des planches entre elles.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from statistics import median

import numpy as np

from .geometry import Drawing
from .sheets import Sheet, crop


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


# ----------------------------------------------------------------------------- noms de niveaux
ROOF_NAMES = ("TERRASSE", "TOITURE")


ELEV_RE = re.compile(r"([±+\-]|^|\s)\s*(\d{1,3})[,.](\d{2,3})\b")


def level_elevation(text: str) -> float | None:
    """Cote écrite dans l'étiquette (« +3,200 », « ±0,00 », « -1.50 ») en m, sinon None."""
    m = re.search(r"([±+\-])\s*(\d{1,3})[,.](\d{2,3})\b", text)
    if not m:
        return None
    v = float(f"{m.group(2)}.{m.group(3)}")
    return -v if m.group(1) == "-" else v


def canonical_level(text: str) -> str | None:
    """« Etage 1 » → « ETAGE 1 », « R.D.C » → « RDC », « Rez-de-jardin » → « RDJ »…"""
    t = _norm(re.sub(ELEV_RE, " ", text)).replace(".", "").replace("-", " ").strip()
    t = re.sub(r"^0 (?=RDC|REZ)", "", t)          # « 0 Rez-de-chaussée » (étiquettes Revit)
    if re.fullmatch(r"(RDJ|REZ DE JARDIN)", t):
        return "RDJ"
    if re.fullmatch(r"(SOUS SOL|SS|SOUS SOL \d|SS\d)", t):
        n = re.findall(r"\d", t)
        return f"SOUS-SOL {n[0]}" if n else "SOUS-SOL"
    if re.fullmatch(r"(RDC|REZ DE CHAUSSEE)", t):
        return "RDC"
    m = re.fullmatch(r"(?:ETAGE|NIVEAU|NIV) ?(\d{1,2})|(\d{1,2}) ?(?:ER|EME|E)? ?ETAGE|R ?\+ ?(\d{1,2})", t)
    if m:
        n = next(g for g in m.groups() if g)
        return f"ETAGE {int(n)}"
    if t in ROOF_NAMES:
        return t
    return None


def level_order_key(name: str) -> int:
    if name.startswith("SOUS-SOL"):
        n = re.findall(r"\d", name)
        return -10 - (int(n[0]) if n else 1)
    order = {"RDJ": -1, "RDC": 0, "TERRASSE": 100, "TOITURE": 101}
    if name in order:
        return order[name]
    return int(name.split()[-1])


def display_name(name: str) -> str:
    if name.startswith("ETAGE"):
        return f"Étage {name.split()[-1]}"
    return {"TERRASSE": "Terrasse", "TOITURE": "Toiture"}.get(name, name.title() if "SOUS" in name else name)


@dataclass
class LevelInfo:
    name: str          # nom canonique (« RDC », « ETAGE 1 »…)
    elevation: float   # m, relatif au plus bas niveau trouvé


def read_elevations(drawing: Drawing, sheets: list[Sheet]) -> tuple[list[LevelInfo], list[str]]:
    """Lit les étiquettes de niveaux alignées verticalement sur les coupes et façades.

    Chaque colonne d'étiquettes (même abscisse) donne des écarts entre niveaux successifs ;
    on retient la médiane de chaque écart sur l'ensemble des coupes et façades.
    """
    notes: list[str] = []
    gaps: dict[tuple[str, str], list[float]] = {}
    def inside(t, b):
        return b[0] <= t.x <= b[2] and b[1] <= t.y <= b[3]

    sources = [crop(drawing, sh.bbox).texts for sh in sheets if not sh.is_plan]
    # coupes et façades hors cadre (dessins sans planches pour elles)
    sources.append([t for t in drawing.texts if not any(inside(t, sh.bbox) for sh in sheets)])
    for texts in sources:
        labels = [(t.x, t.y, canonical_level(t.text), level_elevation(t.text)) for t in texts]
        labels = [lb for lb in labels if lb[2]]
        groups: dict[int, list[tuple[float, str, float | None]]] = {}
        for x, y, n, z in labels:
            groups.setdefault(round(x / 0.5), []).append((y, n, z))
        for g in groups.values():
            names = {n for _, n, _ in g}
            if len(names) < 3:
                continue
            by_name: dict[str, float] = {}
            written = all(z is not None for _, _, z in g)   # cotes écrites : plus sûres que l'espacement
            for y, n, z in g:
                by_name.setdefault(n, z if written else y)
            seq = sorted(by_name.items(), key=lambda kv: kv[1])
            for (n1, y1), (n2, y2) in zip(seq, seq[1:]):
                if level_order_key(n2) > level_order_key(n1):
                    gaps.setdefault((n1, n2), []).append(y2 - y1)
    if not gaps:
        return [], ["Aucune cote de niveau trouvée sur les coupes ou façades."]
    # Chaîne des niveaux du plus bas au plus haut
    names = sorted({n for pair in gaps for n in pair}, key=level_order_key)
    # écart direct entre niveaux consécutifs de la liste (médiane)
    levels = [LevelInfo(names[0], 0.0)]
    for n1, n2 in zip(names, names[1:]):
        vals = gaps.get((n1, n2))
        if not vals:
            notes.append(f"Hauteur {display_name(n1)} → {display_name(n2)} introuvable.")
            break
        h = round(median(vals), 2)
        spread = max(vals) - min(vals)
        if spread > 0.05:
            notes.append(f"{display_name(n1)} → {display_name(n2)} : cotes divergentes "
                         f"({', '.join(f'{v:.2f}' for v in sorted(set(round(v, 2) for v in vals)))} m) ; "
                         f"retenu {h:.2f} m (médiane).")
        levels.append(LevelInfo(n2, round(levels[-1].elevation + h, 2)))
    # « Toiture » juste au-dessus de la terrasse = acrotère / édicule, pas un niveau
    out: list[LevelInfo] = []
    for lv in levels:
        if lv.name == "TOITURE" and out and out[-1].name == "TERRASSE":
            if lv.elevation - out[-1].elevation < 2.5:
                notes.append(f"« Toiture » à {lv.elevation - out[-1].elevation:.2f} m au-dessus de la terrasse : "
                             "acrotère ou édicule, non compté comme niveau.")
                continue
        out.append(lv)
    return out, notes


# ----------------------------------------------------------------------------- planches ↔ niveaux
def sheet_levels(title: str) -> tuple[list[str], bool]:
    """Niveaux désignés par un titre de planche, et s'il s'agit d'un « étage courant »."""
    t = _norm(title).replace("-", " ")
    found: list[str] = []
    if re.search(r"REZ DE JARDIN|\bRDJ\b", t):
        found.append("RDJ")
    if re.search(r"SOUS SOL", t):
        found.append("SOUS-SOL")
    if re.search(r"\bR\.?D\.?C\b|REZ DE CHAUSSEE", t):
        found.append("RDC")
    courant = "COURANT" in t
    m = re.search(r"ETAGES?(?: COURANTS?)?((?:\s*(?:\d{1,2}|ET|A|AU|,|-|&))+)", t)
    if m:
        nums = [int(n) for n in re.findall(r"\d{1,2}", m.group(1))]
        if re.search(r"\d\s*(A|AU|-)\s*\d", m.group(1)) and len(nums) >= 2:
            nums = list(range(nums[0], nums[-1] + 1))
        found += [f"ETAGE {n}" for n in nums]
    for n in re.findall(r"(\d{1,2}) ?(?:ER|EME|E) ETAGE", t):
        found.append(f"ETAGE {int(n)}")
    if "TERRASSE" in t or "TOITURE" in t:
        found.append("TERRASSE")
    if re.search(r"\bETAGES?\b", t) and not any(f.startswith("ETAGE") for f in found):
        courant = True          # « PLAN COTE ETAGE » sans numéro : étage(s) courant(s)
    return list(dict.fromkeys(found)), courant


@dataclass
class StoreyPlan:
    name: str            # niveau canonique (bas de l'étage)
    height: float
    sheet: Sheet | None
    reason: str = ""


def assign_sheets(levels: list[LevelInfo], sheets: list[Sheet],
                  overrides: dict[str, int] | None = None) -> tuple[list[StoreyPlan], list[str]]:
    """Affecte une planche à chaque étage (du bas vers le haut, toit exclu)."""
    notes: list[str] = []
    plans = [s for s in sheets if s.is_plan]
    by_level: dict[str, list[Sheet]] = {}
    courant: list[Sheet] = []
    for s in plans:
        names, is_cur = sheet_levels(s.title)
        for n in names:
            by_level.setdefault(n, []).append(s)
        if is_cur:
            courant.append(s)
    storeys: list[StoreyPlan] = []
    for lo, hi in zip(levels, levels[1:]):
        h = round(hi.elevation - lo.elevation, 2)
        sp = StoreyPlan(lo.name, h, None)
        if overrides and lo.name in overrides:
            sp.sheet = next((s for s in sheets if s.index == overrides[lo.name]), None)
            sp.reason = "imposée"
        elif lo.name in by_level:
            cands = by_level[lo.name]
            sp.sheet = cands[0]
            sp.reason = "titre" if len(cands) == 1 else "titre (plusieurs candidates)"
        elif lo.name.startswith("ETAGE") and courant:
            sp.sheet = courant[0]
            sp.reason = "étage courant"
        storeys.append(sp)
    # étages sans planche : planche de l'étage le plus proche au-dessus, sinon en dessous
    for k, sp in enumerate(storeys):
        if sp.sheet is None:
            src = next((storeys[j] for j in range(k + 1, len(storeys)) if storeys[j].sheet), None) or \
                next((storeys[j] for j in range(k - 1, -1, -1) if storeys[j].sheet), None)
            if src:
                sp.sheet, sp.reason = src.sheet, f"aucune planche : reprise de {display_name(src.name)}"
                notes.append(f"{display_name(sp.name)} : aucune planche trouvée, plan de "
                             f"{display_name(src.name)} utilisé (à vérifier).")
    return storeys, notes


# ----------------------------------------------------------------------------- calage
def align_points(a: np.ndarray, b: np.ndarray, tol: float = 0.25) -> tuple[np.ndarray, int]:
    """Translation t telle que a + t ≈ b (vote sur les différences de positions)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros(2), 0
    diffs = (b[None, :, :] - a[:, None, :]).reshape(-1, 2)
    q = np.round(diffs / 0.1).astype(int)
    vals, cnt = np.unique(q, axis=0, return_counts=True)
    best_t, best_m = np.zeros(2), -1
    for v in vals[np.argsort(-cnt)[:40]]:
        t = v * 0.1
        d = np.linalg.norm((a + t)[:, None, :] - b[None, :, :], axis=2)
        close = d.min(axis=1) < tol
        m = int(close.sum())
        if m > best_m:
            # affinage : moyenne des écarts des poteaux appariés
            j = d.argmin(axis=1)
            t = t + (b[j[close]] - (a[close] + t)).mean(axis=0) if m else t
            best_t, best_m = t, m
    return best_t, best_m


@dataclass
class ColumnStack:
    """Poteaux superposés d'un niveau à l'autre (même repère global)."""
    id: str
    x: float
    y: float
    members: dict[int, str] = field(default_factory=dict)  # indice d'étage → id local
