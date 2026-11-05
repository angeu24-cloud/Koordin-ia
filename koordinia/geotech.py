"""Rapport géotechnique : extraction des données utiles au dimensionnement des fondations.

Chaque valeur extraite est accompagnée de la phrase du rapport dont elle provient.
Les valeurs sont enregistrées dans geotech.json avec « valide » = false : l'ingénieur
les contrôle, les corrige si besoin et passe « valide » à true.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

# conversion vers le MPa
UNITS_MPA = {
    "bar": 0.1, "bars": 0.1, "kpa": 0.001, "mpa": 1.0, "kn/m2": 0.001, "kn/m²": 0.001,
    "kg/cm2": 0.0981, "kg/cm²": 0.0981, "kgf/cm2": 0.0981, "kgf/cm²": 0.0981,
    "t/m2": 0.00981, "t/m²": 0.00981, "daN/cm2".lower(): 0.1, "dan/cm²": 0.1,
}
NUM = r"(\d+(?:[.,]\d+)?)"
PRESSURE_UNIT = r"(bars?|kpa|mpa|kn\s*/\s*m\s*[²2]|kgf?\s*/\s*cm\s*[²2]|t\s*/\s*m\s*[²2]|dan\s*/\s*cm\s*[²2])"
FORCE_UNITS_KN = {"kn": 1.0, "mn": 1000.0, "t": 9.81, "tonnes": 9.81, "tf": 9.81, "dan": 0.01}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


@dataclass
class Value:
    value: float | str
    unit: str
    source: str            # extrait du rapport
    page: int | None = None


@dataclass
class GeotechData:
    fichier: str = ""
    valide: bool = False
    contrainte_admissible_els: Value | None = None   # MPa
    contrainte_elu: Value | None = None              # MPa
    profondeur_ancrage: Value | None = None          # m
    type_fondation: Value | None = None              # « superficielles », « filantes », « radier », « pieux »
    nappe: Value | None = None                       # m sous le TN, ou « absente »
    tassement: Value | None = None                   # cm
    classe_sismique: Value | None = None
    charge_pieu: Value | None = None                 # kN (charge admissible par pieu)
    diametre_pieu: Value | None = None               # m
    candidats: dict[str, list[dict]] = field(default_factory=dict)
    remarques: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GeotechData":
        g = cls(fichier=d.get("fichier", ""), valide=bool(d.get("valide", False)),
                candidats=d.get("candidats", {}), remarques=d.get("remarques", []))
        for k in ("contrainte_admissible_els", "contrainte_elu", "profondeur_ancrage", "type_fondation", "nappe",
                  "tassement", "classe_sismique", "charge_pieu", "diametre_pieu"):
            v = d.get(k)
            if isinstance(v, dict):
                setattr(g, k, Value(**v))
            elif v is not None:  # valeur saisie directement par l'ingénieur
                setattr(g, k, Value(v, "", "saisie manuelle"))
        return g

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "GeotechData":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # valeurs numériques pratiques
    @property
    def sigma_sol(self) -> float | None:
        v = self.contrainte_admissible_els
        return float(v.value) if v and isinstance(v.value, (int, float)) else None

    @property
    def depth(self) -> float | None:
        v = self.profondeur_ancrage
        return float(v.value) if v and isinstance(v.value, (int, float)) else None

    @property
    def foundation(self) -> str:
        v = self.type_fondation
        return str(v.value) if v else "superficielles"

    @property
    def water_depth(self) -> float | None:
        v = self.nappe
        return float(v.value) if v and isinstance(v.value, (int, float)) else None


# ----------------------------------------------------------------------------- lecture du texte
def read_text(path: str | Path) -> list[tuple[int, str]]:
    """Texte du rapport, page par page (PDF texte, TXT ; DOCX si python-docx est installé)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf

        doc = pymupdf.open(path)
        pages = [(i + 1, p.get_text()) for i, p in enumerate(doc)]
        if sum(len(t.strip()) for _, t in pages) < 40:
            raise ValueError("Ce PDF ne contient pas de texte (rapport scanné) : la lecture automatique n'est pas "
                             "possible. Créez un geotech.json vierge (koordinia geotech --vierge) et saisissez "
                             "les valeurs du rapport.")
        return pages
    if suffix in (".txt", ".md"):
        return [(1, path.read_text(encoding="utf-8", errors="replace"))]
    if suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ValueError("Lecture .docx : installez python-docx, ou exportez le rapport en PDF.") from exc
        d = docx.Document(str(path))
        return [(1, "\n".join(p.text for p in d.paragraphs))]
    raise ValueError(f"Format de rapport non pris en charge : {suffix} (PDF, TXT, DOCX)")


def _sentences(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out = []
    for no, txt in pages:
        flat = re.sub(r"[ \t]+", " ", txt.replace("\r", ""))
        flat = re.sub(r"-\n(\w)", r"\1", flat)           # césures
        flat = re.sub(r"(?<![.:;!?])\n(?!\n)", " ", flat)  # retours à la ligne dans une phrase
        for s in re.split(r"(?<=[.;!?])\s+|\n{2,}|\n(?=[-•*]\s)", flat):
            s = s.strip()
            if len(s) > 8:
                out.append((no, s))
    return out


def _pressure(num: str, unit: str) -> float:
    u = re.sub(r"\s+", "", unit.lower()).replace("²", "2")
    for k, f in UNITS_MPA.items():
        if re.sub(r"\s+", "", k).replace("²", "2") == u:
            return float(num.replace(",", ".")) * f
    return float("nan")


# ----------------------------------------------------------------------------- extraction
def extract(path: str | Path) -> GeotechData:
    pages = read_text(path)
    sents = _sentences(pages)
    g = GeotechData(fichier=str(path))
    cands: dict[str, list[dict]] = {}

    def add(key: str, value, unit: str, no: int, sentence: str, score: float = 0.0) -> None:
        cands.setdefault(key, []).append({"value": value, "unit": unit, "source": sentence[:300], "page": no,
                                          "score": score})

    for no, s in sents:
        n = _norm(s)
        # --- contraintes / capacité portante
        if re.search(r"contrainte|taux de travail|pression|capacite portante|portance|q\s*_?adm|sigma|σ|qu\b|q\s*ref", n):
            for m in re.finditer(NUM + r"\s*" + PRESSURE_UNIT, n):
                val = _pressure(m.group(1), m.group(2))
                if not (0.01 <= val <= 5.0):
                    continue
                near = n[max(0, m.start() - 60):m.start()]
                ctx = n[max(0, m.start() - 90):m.end() + 20]
                is_elu = bool(re.search(r"\belu\b|ultime|rupture|limite", near))
                is_els = bool(re.search(r"\bels\b|admissible|service|q\s*_?adm|taux de travail", ctx))
                if is_elu and not re.search(r"\bels\b|admissible|service", near):
                    add("contrainte_elu", round(val, 4), "MPa", no, s, 1)
                    continue
                score = (2 if is_els else 0) + (1 if "admissible" in ctx else 0)
                add("contrainte_admissible_els", round(val, 4), "MPa", no, s, score)
        # --- profondeur d'ancrage
        if re.search(r"ancr|assise|fond de fouille|encastr|profondeur", n) and not re.search(r"nappe|eau", n):
            for m in re.finditer(r"(?:-|a|de|sous|minimum|min\.?|d'au moins|>=|≥)?\s*" + NUM + r"\s*m(?:etres?)?\b", n):
                val = float(m.group(1).replace(",", "."))
                if 0.3 <= val <= 15:
                    add("profondeur_ancrage", val, "m", no, s, 1 if re.search(r"ancr|assise", n) else 0)
        # --- nappe
        if re.search(r"nappe|niveau d.eau|venue.? d.eau|eau a ", n):
            if re.search(r"(pas|aucune?|absence)( de)? (nappe|venue|eau)|n.a pas ete (rencontree|observee)|non rencontree", n):
                add("nappe", "absente", "", no, s, 1)
            else:
                for m in re.finditer(NUM + r"\s*m\b", n):
                    val = float(m.group(1).replace(",", "."))
                    if 0.1 <= val <= 50:
                        add("nappe", val, "m/TN", no, s)
        # --- tassements
        if "tassement" in n:
            for m in re.finditer(NUM + r"\s*(cm|mm)\b", n):
                val = float(m.group(1).replace(",", ".")) * (0.1 if m.group(2) == "mm" else 1.0)
                if 0 < val < 50:
                    add("tassement", round(val, 2), "cm", no, s)
        # --- classe de sol sismique
        m = re.search(r"classe de sol\s*:?\s*([a-e])\b|site\s*(s[0-4])\b|sol de (?:classe|type)\s*([a-e])\b", n)
        if m:
            add("classe_sismique", next(x for x in m.groups() if x).upper(), "", no, s)
        # --- type de fondation recommandé
        reco = bool(re.search(r"recommand|preconis|conseill|envisag|opter|retenir|adopter|prevoir|proposons|"
                              r"sera(?:ient)? (?:realise|fonde)|fonder|fondation.? de type|type de fondation", n))
        types = []
        if re.search(r"\bpieux?\b|micro.?pieux|fondations? profondes?|barrettes", n):
            types.append("pieux")
        if "radier" in n:
            types.append("radier")
        if re.search(r"semelles? filantes?", n):
            types.append("filantes")
        if re.search(r"semelles? isolees?|fondations? superficielles?|semelles? superficielles?", n):
            types.append("superficielles")
        if re.search(r"(deconseill|exclu|a eviter|pas envisageable|ne (sont|est) pas (envisageable|adapte))", n):
            types = []
        for t in types:
            add("type_fondation", t, "", no, s, 2 if reco else 0)
        # --- pieux : charge admissible et diamètre
        if re.search(r"pieu", n):
            for m in re.finditer(NUM + r"\s*(kn|mn|tonnes|tf|t|dan)\b", n):
                f = FORCE_UNITS_KN[m.group(2)]
                val = float(m.group(1).replace(",", ".")) * f
                if 50 <= val <= 20000 and re.search(r"admissible|nominale|service|qadm|portance|capacite|charge", n):
                    add("charge_pieu", round(val, 1), "kN", no, s)
            m = re.search(r"(?:diametre|o|ø)\s*=?\s*" + NUM + r"\s*(mm|cm|m)\b", n)
            if m:
                v = float(m.group(1).replace(",", ".")) * {"mm": 0.001, "cm": 0.01, "m": 1.0}[m.group(2)]
                if 0.2 <= v <= 2.0:
                    add("diametre_pieu", v, "m", no, s)

    g.candidats = cands

    def pick(key: str, how: str = "score") -> Value | None:
        lst = cands.get(key)
        if not lst:
            return None
        if key == "contrainte_admissible_els":
            # valeur explicitement « admissible / ELS » la plus défavorable (la plus faible)
            best = max(c["score"] for c in lst)
            top = [c for c in lst if c["score"] == best]
            c = min(top, key=lambda c: c["value"])
            if len({round(x["value"], 3) for x in top}) > 1:
                g.remarques.append("Plusieurs contraintes admissibles dans le rapport : la plus faible est retenue "
                                   f"({', '.join(f'{x['value']:g}' for x in top)} MPa) — vérifier selon la zone.")
        elif key == "type_fondation":
            score: dict[str, float] = {}
            for c in lst:
                score[c["value"]] = score.get(c["value"], 0) + 1 + c["score"]
            v = max(score, key=score.get)
            c = next(c for c in sorted(lst, key=lambda c: -c["score"]) if c["value"] == v)
        elif key == "nappe":
            nums = [c for c in lst if isinstance(c["value"], float)]
            c = min(nums, key=lambda c: c["value"]) if nums else lst[0]
        elif key == "profondeur_ancrage":
            c = max(lst, key=lambda c: (c["score"], c["value"]))
        else:
            c = max(lst, key=lambda c: c["score"])
        return Value(c["value"], c["unit"], c["source"], c["page"])

    for key in ("contrainte_admissible_els", "contrainte_elu", "profondeur_ancrage", "type_fondation", "nappe",
                "tassement", "classe_sismique", "charge_pieu", "diametre_pieu"):
        setattr(g, key, pick(key))
    if g.contrainte_admissible_els is None and g.contrainte_elu is not None:
        v = float(g.contrainte_elu.value) / 1.5
        g.contrainte_admissible_els = Value(round(v, 4), "MPa",
                                            f"déduite de la contrainte ELU / 1,5 — {g.contrainte_elu.source}",
                                            g.contrainte_elu.page)
        g.remarques.append("Contrainte ELS non trouvée : prise égale à la contrainte ELU / 1,5 (à confirmer).")
    if g.contrainte_admissible_els is None:
        g.remarques.append("Contrainte admissible introuvable : à saisir dans geotech.json.")
    if g.type_fondation is None:
        g.remarques.append("Type de fondation non identifié : semelles isolées par défaut.")
    return g


def summary_lines(g: GeotechData) -> list[tuple[str, str, str]]:
    def fmt(v: Value | None, unit: str = "") -> str:
        if v is None:
            return "—"
        if isinstance(v.value, float):
            return f"{v.value:g} {v.unit or unit}".strip()
        return f"{v.value} {v.unit}".strip()

    rows = [
        ("Contrainte admissible (ELS)", fmt(g.contrainte_admissible_els), g.contrainte_admissible_els),
        ("Contrainte ELU", fmt(g.contrainte_elu), g.contrainte_elu),
        ("Profondeur d'ancrage", fmt(g.profondeur_ancrage), g.profondeur_ancrage),
        ("Type de fondation", fmt(g.type_fondation), g.type_fondation),
        ("Nappe", fmt(g.nappe), g.nappe),
        ("Tassement", fmt(g.tassement), g.tassement),
        ("Classe de sol sismique", fmt(g.classe_sismique), g.classe_sismique),
        ("Charge admissible par pieu", fmt(g.charge_pieu), g.charge_pieu),
        ("Diamètre des pieux", fmt(g.diametre_pieu), g.diametre_pieu),
    ]
    return [(k, v, (f"p.{src.page} : « {src.source} »" if src and src.page else (src.source if src else "")))
            for k, v, src in rows]
