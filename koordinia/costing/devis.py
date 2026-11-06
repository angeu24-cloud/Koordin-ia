"""Devis quantitatif et estimatif (DQE) : métré × bordereau de prix → Excel avec formules."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .bpu import Bordereau, norm
from .metre import DevisSettings, compute_metre

OUVRAGES_PATH = Path(__file__).resolve().parent.parent / "data" / "ouvrages.json"


@dataclass
class DevisLine:
    code: str
    lot: str
    designation: str
    unit: str
    quantity: float
    pu_ht: float | None
    price_ref: str = ""        # chemin de la ligne du bordereau
    price_row: int | None = None
    details: list = field(default_factory=list)

    @property
    def amount(self) -> float:
        return round(self.quantity * (self.pu_ht or 0.0), 0)


@dataclass
class Devis:
    project: str
    currency: str
    tva: float
    bpu_source: str
    lines: list[DevisLine]
    notes: list[str] = field(default_factory=list)

    @property
    def total_ht(self) -> float:
        return sum(ln.amount for ln in self.lines)

    def lots(self) -> list[tuple[str, list[DevisLine]]]:
        out: dict[str, list[DevisLine]] = {}
        for ln in self.lines:
            out.setdefault(ln.lot, []).append(ln)
        return list(out.items())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_ht"] = self.total_ht
        d["tva_montant"] = round(self.total_ht * self.tva, 0)
        d["total_ttc"] = round(self.total_ht * (1 + self.tva), 0)
        for ln, dl in zip(self.lines, d["lines"]):
            dl["amount"] = ln.amount
        return d


def load_rules(extra: list[dict] | None = None) -> list[dict]:
    rules = json.loads(OUVRAGES_PATH.read_text(encoding="utf-8"))["ouvrages"]
    if extra:
        by_code = {r["code"]: r for r in rules}
        for r in extra:
            by_code[r["code"]] = {**by_code.get(r["code"], {}), **r}
        rules = list(by_code.values())
    return rules


FOSSE_SIZES = [5, 10, 15, 20, 30, 40, 50, 70, 90, 100]


def build_devis(res, bpu: Bordereau | None, settings: DevisSettings, rules_extra: list[dict] | None = None,
                mep=None) -> Devis:
    metre = compute_metre(res, settings)
    if settings.second_oeuvre:
        from .archi import archi_metre

        metre.update(archi_metre(res, settings))
    usagers = 0
    if mep is not None:
        from .metre import Quantity

        for code, (qty, det) in mep.quantities.items():
            qq = Quantity(code)
            for lbl, v in det:
                qq.add(lbl, v)
            metre[code] = qq
        import re as _re

        m = next((_re.search(r"(\d+) usagers", lbl) for lbl, v in mep.quantities.get("PL-FOS", [0, []])[1]), None)
        usagers = int(m.group(1)) if m else 0
    rules = load_rules(rules_extra)
    fosse = next((n for n in FOSSE_SIZES if n >= usagers), FOSSE_SIZES[-1]) if usagers else 10
    subst = {"categorie": settings.categorie, "dosage": str(settings.dosage),
             "hourdis": norm(settings.hourdis).replace("+", r"\+"), "usagers": str(fosse)}
    lines: list[DevisLine] = []
    missing = []
    for r in rules:
        qty = metre.get(r["code"])
        if not qty:
            continue
        motifs = [m.format(**subst) for m in r.get("motifs", [])]
        item = bpu.find(motifs) if bpu else None
        des = r["designation"].format(**{**subst, "hourdis": settings.hourdis})
        unit = r["unite"]
        if item and norm(item.unit).rstrip(".") not in (norm(unit), norm(unit).replace("2", "²")):
            pass  # unités du bordereau parfois écrites autrement (m², m2…) : on garde celle de l'ouvrage
        ln = DevisLine(r["code"], r["lot"], des, unit, round(qty.quantity, 2 if unit != "kg" else 0),
                       round(item.pu_ht, 0) if item else None, item.path if item else "",
                       item.row if item else None, [(a, round(b, 3)) for a, b in qty.details])
        if not item:
            missing.append(des)
        lines.append(ln)
    notes = []
    if bpu is None:
        notes.append("Aucun bordereau de prix : devis quantitatif seul (prix unitaires à saisir).")
    elif missing:
        notes.append(f"{len(missing)} ouvrage(s) sans prix dans le bordereau : {', '.join(missing)}.")
    if settings.second_oeuvre:
        notes.append("Métré tiré du calcul (structure) et des plans d'architecte (murs, ouvertures, locaux) : "
                     "maçonnerie, enduits, sols, faïence, étanchéité, menuiseries, peinture" +
                     (" ; réseaux (plomberie, électricité, climatisation) pré-dimensionnés." if mep is not None else
                      ". Hors lots techniques."))
    if usagers and usagers > FOSSE_SIZES[-1]:
        notes.append(f"Fosse septique : {usagers} usagers estimés > {FOSSE_SIZES[-1]} (plusieurs fosses ou "
                     "raccordement au réseau public).")
    else:
        notes.append("Métré du gros œuvre de structure seul (second œuvre désactivé).")
    return Devis(res.project.name or "", bpu.currency if bpu else "FCFA", settings.tva,
                 bpu.source if bpu else "", lines, notes)


# ----------------------------------------------------------------------------- Excel
def write_excel(devis: Devis, path: str | Path) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DQE"
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    lot_fill = PatternFill("solid", fgColor="DDE7F0")
    miss_fill = PatternFill("solid", fgColor="FDE2E1")
    money = '#,##0'
    ws["A1"] = "DEVIS QUANTITATIF ET ESTIMATIF — GROS ŒUVRE DE STRUCTURE"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Projet : {devis.project}"
    ws["A3"] = f"Bordereau de prix : {devis.bpu_source or '— (prix à saisir)'} — montants en {devis.currency}"
    ws["A3"].font = Font(italic=True, color="555555")
    headers = ["N°", "Désignation", "Unité", "Quantité", f"P.U HT ({devis.currency})", f"Montant HT ({devis.currency})"]
    r = 5
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(r, c, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    r += 1
    lot_totals = []
    for li, (lot, lines) in enumerate(devis.lots(), start=1):
        ws.cell(r, 1, f"{li}").font = Font(bold=True)
        ws.cell(r, 2, f"LOT {li} — {lot}").font = Font(bold=True)
        for c in range(1, 7):
            ws.cell(r, c).fill = lot_fill
            ws.cell(r, c).border = border
        r += 1
        first = r
        for k, ln in enumerate(lines, start=1):
            ws.cell(r, 1, f"{li}.{k}")
            ws.cell(r, 2, ln.designation).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(r, 3, ln.unit)
            ws.cell(r, 4, ln.quantity).number_format = '#,##0.00'
            pu = ws.cell(r, 5, ln.pu_ht)
            pu.number_format = money
            if ln.pu_ht is None:
                pu.fill = miss_fill
            amt = ws.cell(r, 6, f"=D{r}*E{r}")
            amt.number_format = money
            for c in range(1, 7):
                ws.cell(r, c).border = border
            r += 1
        ws.cell(r, 2, f"Sous-total lot {li} — {lot}").font = Font(bold=True)
        st = ws.cell(r, 6, f"=SUM(F{first}:F{r - 1})")
        st.number_format = money
        st.font = Font(bold=True)
        for c in range(1, 7):
            ws.cell(r, c).border = border
        lot_totals.append(f"F{r}")
        r += 2
    ws.cell(r, 2, "TOTAL HT").font = Font(bold=True)
    tot = ws.cell(r, 6, "=" + "+".join(lot_totals) if lot_totals else 0)
    tot.number_format = money
    tot.font = Font(bold=True)
    r_ht = r
    r += 1
    ws.cell(r, 2, "Taux de TVA")
    ws.cell(r, 5, devis.tva).number_format = "0.0%"
    r_tva_rate = r
    ws.cell(r, 6, f"=F{r_ht}*E{r_tva_rate}").number_format = money
    r_tva = r
    r += 1
    ws.cell(r, 2, "TOTAL TTC").font = Font(bold=True, size=12)
    ttc = ws.cell(r, 6, f"=F{r_ht}+F{r_tva}")
    ttc.number_format = money
    ttc.font = Font(bold=True, size=12)
    r += 2
    for n in devis.notes:
        ws.cell(r, 2, n).font = Font(italic=True, color="555555")
        r += 1
    ws.cell(r, 2, "Document généré par Koordin-IA à partir du calcul : à vérifier par l'économiste / l'ingénieur.").font = \
        Font(italic=True, color="9A6700")
    for c, wdt in enumerate([8, 70, 8, 14, 16, 20], start=1):
        ws.column_dimensions[get_column_letter(c)].width = wdt
    ws.freeze_panes = "A6"

    # --- métré détaillé
    wm = wb.create_sheet("Métré")
    wm.append(["Ouvrage", "Élément / formule", "Quantité", "Unité"])
    for c in range(1, 5):
        wm.cell(1, c).font = Font(bold=True)
    for ln in devis.lines:
        wm.append([ln.designation, "", None, None])
        wm.cell(wm.max_row, 1).font = Font(bold=True)
        for label, qv in ln.details:
            wm.append(["", label, qv, ln.unit])
        wm.append(["", "Total", ln.quantity, ln.unit])
        wm.cell(wm.max_row, 2).font = Font(bold=True)
    for c, wdt in enumerate([45, 70, 12, 8], start=1):
        wm.column_dimensions[get_column_letter(c)].width = wdt

    # --- origine des prix
    wp = wb.create_sheet("Prix")
    wp.append(["Code", "Ouvrage", "Ligne du bordereau", "Article du bordereau", "P.U HT"])
    for c in range(1, 6):
        wp.cell(1, c).font = Font(bold=True)
    for ln in devis.lines:
        wp.append([ln.code, ln.designation, ln.price_row, ln.price_ref or "— à saisir —", ln.pu_ht])
    for c, wdt in enumerate([10, 50, 10, 90, 14], start=1):
        wp.column_dimensions[get_column_letter(c)].width = wdt
    path = Path(path)
    wb.save(path)
    return path
