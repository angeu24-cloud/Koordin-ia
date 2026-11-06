"""Bordereau des prix unitaires (BPU) : import Excel (.xls/.xlsx) ou CSV.

Les bordereaux sont souvent sans numéro d'article, avec des libellés répétés
(« 1ère catégorie » sous plusieurs types de fouilles) : chaque prix est donc repéré
par son chemin complet « Lot > chapitre > sous-chapitre > désignation ».
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path


def norm(s: str) -> str:
    s = str(s or "").replace("œ", "oe").replace("Œ", "OE").replace("²", "2").replace("³", "3")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\s*\+\s*", " + ", s)
    return re.sub(r"\s+", " ", s).strip().upper()


@dataclass
class PriceItem:
    ref: str              # référence (n° d'article ou « L<lot>.<ligne> »)
    lot: str
    chapter: str          # chapitres parents, séparés par « > »
    designation: str
    unit: str
    pu_ht: float | None
    pu_ttc: float | None = None
    row: int = 0          # ligne du fichier source (1 = première ligne)

    @property
    def path(self) -> str:
        return " > ".join(x for x in (self.lot, self.chapter, self.designation) if x)


@dataclass
class Bordereau:
    source: str = ""
    sheet: str = ""
    currency: str = "FCFA"
    items: list[PriceItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"source": self.source, "sheet": self.sheet, "currency": self.currency, "notes": self.notes,
                "items": [asdict(i) for i in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> "Bordereau":
        return cls(d.get("source", ""), d.get("sheet", ""), d.get("currency", "FCFA"),
                   [PriceItem(**i) for i in d.get("items", [])], d.get("notes", []))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=0), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Bordereau":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def find(self, patterns: list[str]) -> PriceItem | None:
        """Première ligne dont le chemin normalisé contient tous les motifs (expressions régulières)."""
        for it in self.items:
            if it.pu_ht is None:
                continue
            p = norm(it.path)
            if all(re.search(pt, p) for pt in patterns):
                return it
        return None


# ----------------------------------------------------------------------------- lecture des tableurs
def _rows(path: Path) -> tuple[list[list], str]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd

        book = xlrd.open_workbook(str(path))
        sheet = max(book.sheets(), key=lambda s: s.nrows * max(1, s.ncols))
        best = None
        for sh in book.sheets():  # feuille contenant « DESIGNATION » et le plus de colonnes de prix
            txt = " ".join(norm(sh.cell_value(r, c)) for r in range(min(sh.nrows, 60)) for c in range(sh.ncols))
            if "DESIGNATION" in txt and (best is None or sh.ncols > best.ncols):
                best = sh
        sheet = best or sheet
        return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)], sheet.name
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        best, rows_best = None, []
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            txt = " ".join(norm(v) for r in rows[:60] for v in r if v is not None)
            if "DESIGNATION" in txt and (best is None or (rows and len(rows[0]) > len(rows_best[0] if rows_best else []))):
                best, rows_best = ws, rows
        if best is None:
            best = wb.worksheets[0]
            rows_best = [list(r) for r in best.iter_rows(values_only=True)]
        return rows_best, best.title
    if suffix in (".csv", ".txt"):
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(raw[:4000], delimiters=";,\t")
        return [list(r) for r in csv.reader(raw.splitlines(), dialect)], ""
    raise ValueError(f"Format de bordereau non pris en charge : {suffix} (xls, xlsx, csv)")


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).replace(" ", "").replace(" ", ""))
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def import_bpu(path: str | Path) -> Bordereau:
    path = Path(path)
    rows, sheet = _rows(path)
    bpu = Bordereau(source=path.name, sheet=sheet)
    # ligne d'en-tête : DESIGNATION + UNITE (+ P.U)
    head, cols = None, {}
    for r, row in enumerate(rows[:200]):
        cells = [norm(v) for v in row]
        if any("DESIGNATION" in c for c in cells) and any(re.match(r"^U(NITE|\.|N)", c) for c in cells):
            head = r
            for c, v in enumerate(cells):
                if "DESIGNATION" in v:
                    cols["des"] = c
                elif re.match(r"^(UNITE|U\.?|UN\.?)$", v) or v.startswith("UNITE"):
                    cols["unit"] = c
                elif re.search(r"P\.?\s?U\.?.*TTC|PRIX.*TTC", v):
                    cols["ttc"] = c
                elif re.search(r"P\.?\s?U\.?.*HT|PRIX.*H\.?T|^P\.?\s?U\.?$|PRIX UNITAIRE", v):
                    cols["ht"] = c
                elif re.match(r"^(N|N°|N0|NO|REF|ART|CODE)", v.replace("°", "")) and "des" not in cols:
                    cols["ref"] = c
            break
    if head is None or "des" not in cols:
        raise ValueError("En-tête du bordereau introuvable (colonnes « Désignation » et « Unité » attendues).")
    if "ht" not in cols and "ttc" not in cols:
        raise ValueError("Colonne de prix unitaire introuvable (« P.U HT », « Prix unitaire »…).")
    lot, stack = "", []
    lot_no = 0
    for r in range(head + 1, len(rows)):
        row = rows[r] + [None] * 20
        des = str(row[cols["des"]] or "").strip()
        if not des:
            continue
        unit = str(row[cols.get("unit", 99)] or "").strip()
        ht = _num(row[cols["ht"]]) if "ht" in cols else None
        ttc = _num(row[cols["ttc"]]) if "ttc" in cols else None
        if ht is None and ttc:
            ht = round(ttc / 1.18, 2)
            if not bpu.notes:
                bpu.notes.append("Prix HT déduits des prix TTC (TVA 18 %).")
        if re.match(r"(?i)^lot\b", des):
            lot, stack = des, []
            m = re.search(r"\d+", des)
            lot_no = int(m.group()) if m else lot_no + 1
            continue
        if not unit:  # titre de chapitre : profondeur déduite de la casse (MAJUSCULES = niveau 1)
            level = 0 if des.isupper() else (1 if not stack or stack[0][1] == 0 else 2)
            stack = [s for s in stack if s[1] < level] + [(des, level)]
            continue
        ref = str(row[cols["ref"]]).strip() if "ref" in cols and row[cols["ref"]] not in (None, "") else ""
        bpu.items.append(PriceItem(ref or f"L{lot_no}.{r + 1}", lot, " > ".join(s[0] for s in stack), des, unit,
                                   ht if ht else None, ttc, r + 1))
    priced = sum(1 for i in bpu.items if i.pu_ht)
    bpu.notes.append(f"{len(bpu.items)} articles lus, dont {priced} avec un prix.")
    return bpu
