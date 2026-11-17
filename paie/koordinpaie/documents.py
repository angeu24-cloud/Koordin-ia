"""Documents : contrat de travail (PDF), bulletin de paie (PDF), livre de paie (Excel)."""
from __future__ import annotations

import io
from datetime import date
from html import escape

from .paie import libelle_periode

CSS = """
* { font-family: sans-serif; }
body { font-size: 9pt; color: #1c2430; }
h1 { font-size: 15pt; text-align: center; margin: 0 0 4pt; }
h2 { font-size: 10.5pt; margin: 7pt 0 2pt; }
p { margin: 0 0 5pt; text-align: justify; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 0.6pt solid #9aa5b1; padding: 2pt 4pt; vertical-align: top; }
th { background-color: #e8eef5; text-align: left; }
.n { text-align: right; }
.c { text-align: center; }
.sans td { border: none; padding: 1pt 2pt; }
.tot td { font-weight: bold; background-color: #f2f5f8; }
.net td { font-weight: bold; font-size: 12pt; background-color: #dbe7f3; }
.petit { font-size: 7.5pt; color: #5d6b7c; }
.bloc { border: 0.6pt solid #9aa5b1; padding: 4pt; }
"""


def fcfa(v, vide: str = "") -> str:
    if v in (None, "") or v == 0:
        return vide
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return escape(str(v))
    return f"{n:,}".replace(",", " ")


def nombre(v) -> str:
    if v in (None, ""):
        return ""
    f = float(v)
    return f"{f:,.2f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",") if f % 1 else fcfa(f, "0")


def taux(t) -> str:
    if t in (None, ""):
        return ""
    return f"{float(t) * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " %"


def date_fr(v) -> str:
    if not v:
        return ""
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return escape(str(v))


def e(v) -> str:
    return escape(str(v)) if v not in (None, "") else ""


def html_vers_pdf(html: str) -> bytes:
    import pymupdf

    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html, user_css=CSS)
    page = pymupdf.paper_rect("a4")
    zone = page + (40, 36, -40, -36)
    plus = True
    while plus:
        dev = writer.begin_page(page)
        plus, _ = story.place(zone)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def assembler(pdfs: list[bytes]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for b in pdfs:
        with pymupdf.open("pdf", b) as src:
            doc.insert_pdf(src)
    return doc.tobytes()


# ---------------------------------------------------------------------------- bulletin de paie
def bulletin_html(b: dict) -> str:
    r, inst = b["resultat"], b["instantane"]
    s, c, ent = inst["salarie"], inst["contrat"], inst.get("entreprise") or {}
    p = b["periode"]
    cu = b.get("cumuls") or {}

    lignes = []
    for g in r["gains"]:
        lignes.append(f"<tr><td>{e(g['libelle'])}</td><td class='n'>{nombre(g.get('base'))}</td>"
                      f"<td class='n'>{taux(g['taux']) if g.get('taux') and g['taux'] < 1 else nombre(g.get('taux'))}</td>"
                      f"<td class='n'>{fcfa(g.get('gain'))}</td><td></td><td></td><td></td></tr>")
    lignes.append(f"<tr class='tot'><td>SALAIRE BRUT</td><td></td><td></td><td class='n'>{fcfa(r['brut'], '0')}</td>"
                  "<td></td><td></td><td></td></tr>")
    for l in r["cotisations"]:
        lignes.append(f"<tr><td>{e(l['libelle'])}</td><td class='n'>{nombre(l.get('base'))}</td>"
                      f"<td class='n'>{taux(l.get('taux'))}</td><td></td>"
                      f"<td class='n'>{fcfa(l.get('retenue'))}</td><td class='n'>{taux(l.get('taux_patronal'))}</td>"
                      f"<td class='n'>{fcfa(l.get('patronal'))}</td></tr>")
    for l in r["retenues"]:
        lignes.append(f"<tr><td>{e(l['libelle'])}</td><td></td><td></td><td></td>"
                      f"<td class='n'>{fcfa(l.get('retenue'))}</td><td></td><td></td></tr>")
    lignes.append(f"<tr class='tot'><td>TOTAUX</td><td></td><td></td><td class='n'>{fcfa(r['brut'], '0')}</td>"
                  f"<td class='n'>{fcfa(r['total_cotisations'] + r['total_retenues'], '0')}</td><td></td>"
                  f"<td class='n'>{fcfa(r['charges_patronales'], '0')}</td></tr>")

    emploi = [("Matricule", e(s.get("matricule"))), ("N° CNPS", e(s.get("numero_cnps"))),
              ("Emploi", e(c.get("poste"))), ("Catégorie", e(c.get("categorie"))),
              ("Contrat", e(c.get("type"))), ("Embauche", date_fr(s.get("date_embauche"))),
              ("Ancienneté", f"{r['anciennete_annees']} an(s)"), ("Parts fiscales", nombre(r["parts"]))]
    cellules = [f"<td width='13%' class='petit'>{k}</td><td width='37%'>{v}</td>" for k, v in emploi]
    info = "".join(f"<tr>{cellules[i]}{cellules[i + 1]}</tr>" for i in range(0, len(cellules), 2))
    adresse_sal = " — ".join(e(x) for x in (s.get("adresse"), s.get("telephone")) if x)
    paiement = " — ".join(x for x in (e(s.get("mode_paiement")), e(s.get("banque")), e(s.get("rib"))) if x)

    return f"""<html><body>
<table class="sans"><tr>
<td width="55%"><b>{e(ent.get('raison_sociale') or 'Entreprise')}</b><br>{e(ent.get('adresse'))} {e(ent.get('ville'))}<br>
<span class="petit">RCCM {e(ent.get('rccm'))}<br>CC {e(ent.get('compte_contribuable'))} — N° employeur CNPS {e(ent.get('numero_cnps'))}</span></td>
<td width="45%" class="n"><b style="font-size:13pt">BULLETIN DE PAIE</b><br>Période : {libelle_periode(p['annee'], p['mois'])}</td></tr></table>
<p></p>
<p style="font-size:11pt"><b>{e(s.get('nom'))} {e(s.get('prenoms'))}</b> <span class="petit">{adresse_sal}</span></p>
<table>{info}</table>
<p class="petit">Paiement : {paiement or '—'}</p>
<table>
<tr><th width="35%">Rubrique</th><th width="11%" class="n">Base</th><th width="9%" class="n">Taux</th>
<th width="12%" class="n">Gains</th><th width="12%" class="n">Retenues</th><th width="8%" class="n">Taux pat.</th>
<th width="13%" class="n">Patronal</th></tr>
{''.join(lignes)}
<tr class="net"><td colspan="4">NET À PAYER</td><td class="n" colspan="3">{fcfa(r['net_a_payer'], '0')} FCFA</td></tr>
</table>
<p></p>
<table>
<tr><th width="16%"></th><th width="14%" class="n">Brut</th><th width="14%" class="n">Imposable</th><th width="14%" class="n">CNPS salarié</th>
<th width="14%" class="n">ITS</th><th width="14%" class="n">Net à payer</th><th width="14%" class="n">Patronal</th></tr>
<tr><td>Mois</td><td class="n">{fcfa(r['brut'], '0')}</td><td class="n">{fcfa(r['brut_imposable'], '0')}</td>
<td class="n">{fcfa(r['cnps_salarie'], '0')}</td><td class="n">{fcfa(r['its'], '0')}</td>
<td class="n">{fcfa(r['net_a_payer'], '0')}</td><td class="n">{fcfa(r['charges_patronales'], '0')}</td></tr>
<tr><td>Cumul {p['annee']}</td><td class="n">{fcfa(cu.get('brut'), '0')}</td><td class="n">{fcfa(cu.get('brut_imposable'), '0')}</td>
<td class="n">{fcfa(cu.get('cnps_salarie'), '0')}</td><td class="n">{fcfa(cu.get('its'), '0')}</td>
<td class="n">{fcfa(cu.get('net_a_payer'), '0')}</td><td class="n">{fcfa(cu.get('charges_patronales'), '0')}</td></tr>
</table>
<p></p>
<p class="petit">Coût total employeur : {fcfa(r['cout_employeur'], '0')} FCFA. Congés payés : 2,2 jours ouvrables acquis par mois de service effectif.
Conservez ce bulletin sans limitation de durée.</p>
</body></html>"""


def bulletin_pdf(b: dict) -> bytes:
    return html_vers_pdf(bulletin_html(b))


# ---------------------------------------------------------------------------- contrat de travail
TITRES = {"CDI": "CONTRAT DE TRAVAIL À DURÉE INDÉTERMINÉE",
          "CDD": "CONTRAT DE TRAVAIL À DURÉE DÉTERMINÉE",
          "JOURNALIER": "CONTRAT DE TRAVAIL JOURNALIER"}

UNITE = {"mensuel": "par mois", "journalier": "par journée de travail", "horaire": "par heure de travail"}


def contrat_html(c: dict, s: dict, ent: dict, avenants: list[dict] | None = None) -> str:
    type_ = c["type"]
    representant = ", ".join(x for x in (e(ent.get("representant")), e(ent.get("qualite_representant"))) if x)
    nom_soc = " ".join(x for x in (f"<b>{e(ent.get('raison_sociale') or '…')}</b>", e(ent.get("forme_juridique")),
                                     f"au capital de {fcfa(ent.get('capital'))} FCFA" if ent.get("capital") else "")
                       if x)
    societe = ", ".join(x for x in (
        nom_soc,
        f"siège social : {e(ent.get('adresse'))} {e(ent.get('ville'))}".strip() if ent.get("adresse") else "",
        f"RCCM {e(ent.get('rccm'))}" if ent.get("rccm") else "",
        f"compte contribuable {e(ent.get('compte_contribuable'))}" if ent.get("compte_contribuable") else "",
        f"n° employeur CNPS {e(ent.get('numero_cnps'))}" if ent.get("numero_cnps") else "") if x)
    naissance = ""
    if s.get("date_naissance"):
        naissance = f", né(e) le {date_fr(s['date_naissance'])}" + (
            f" à {e(s['lieu_naissance'])}" if s.get("lieu_naissance") else "")
    salarie = (f"<b>{e(s.get('nom'))} {e(s.get('prenoms'))}</b>{naissance}"
               + (f", de nationalité {e(s['nationalite'])}" if s.get("nationalite") else "")
               + (f", titulaire de la pièce d'identité n° {e(s['piece_identite'])}" if s.get("piece_identite") else "")
               + (f", demeurant à {e(s['adresse'])}" if s.get("adresse") else ""))
    convention = e(ent.get("convention") or "Convention collective interprofessionnelle du 19 juillet 1977")
    mode = c.get("mode", "mensuel")
    primes = [p for p in c.get("primes_fixes") or [] if p.get("montant")]

    art = []

    def article(titre: str, *paras: str) -> None:
        corps = "".join(f"<p>{x}</p>" for x in paras if x)
        art.append(f"<h2>Article {len(art) + 1} — {titre}</h2>{corps}")

    article("Engagement",
            f"L'Employeur engage le Salarié à compter du <b>{date_fr(c['date_debut'])}</b> en qualité de "
            f"<b>{e(c.get('poste') or '…')}</b>" + (f", catégorie professionnelle <b>{e(c['categorie'])}</b>"
                                                  if c.get("categorie") else "") + ".",
            f"Le présent contrat est régi par la loi n° 2015-532 du 20 juillet 2015 portant Code du travail, "
            f"ses textes d'application, la {convention} et le règlement intérieur de l'entreprise.")
    if type_ == "CDI":
        article("Durée", "Le présent contrat est conclu pour une durée indéterminée.")
    elif type_ == "CDD":
        article("Durée",
                f"Le présent contrat est conclu pour une durée déterminée allant du <b>{date_fr(c['date_debut'])}</b> "
                f"au <b>{date_fr(c.get('date_fin'))}</b>"
                + (f", pour le motif suivant : {e(c['motif_cdd'])}" if c.get("motif_cdd") else "") + ".",
                "Il prend fin de plein droit à son terme. Il peut être renouvelé par avenant écrit ; sa durée totale, "
                "renouvellements compris, ne peut excéder deux ans.")
    else:
        article("Nature de l'engagement",
                "Le Salarié est engagé à la journée, en qualité de travailleur journalier. Sa rémunération est "
                "calculée sur le nombre de journées effectivement travaillées"
                + (f" ; l'engagement prend fin au plus tard le <b>{date_fr(c['date_fin'])}</b>" if c.get("date_fin")
                   else "") + ".")
    if c.get("essai_mois"):
        article("Période d'essai",
                f"Le présent contrat ne deviendra définitif qu'à l'issue d'une période d'essai de "
                f"<b>{nombre(c['essai_mois'])} mois</b>, renouvelable une fois dans les limites fixées par la "
                "convention collective. Pendant cette période, chacune des parties peut rompre le contrat sans "
                "préavis ni indemnité.")
    article("Lieu de travail",
            f"Le Salarié exercera ses fonctions à <b>{e(c.get('lieu') or ent.get('ville') or '…')}</b>. "
            "Il pourra être appelé à se déplacer sur les chantiers et sites de l'entreprise selon les besoins du service.")
    article("Durée du travail",
            f"La durée du travail est fixée à {e(c.get('horaire') or '40 heures par semaine')}. Les heures "
            "supplémentaires effectuées à la demande de l'Employeur sont rémunérées avec les majorations prévues par "
            "la réglementation en vigueur.")
    remu = [f"En contrepartie de son travail, le Salarié percevra un salaire de base de "
            f"<b>{fcfa(c.get('salaire_base'), '0')} FCFA {UNITE.get(mode, '')}</b>."]
    compl = []
    if c.get("sursalaire"):
        compl.append(f"un sursalaire de {fcfa(c['sursalaire'])} FCFA par mois")
    if c.get("transport"):
        compl.append(f"une indemnité de transport de {fcfa(c['transport'])} FCFA par mois")
    for p in primes:
        compl.append(f"{e(p.get('libelle', 'une prime'))} de {fcfa(p['montant'])} FCFA par mois")
    if compl:
        remu.append("S'y ajoutent " + ", ".join(compl) + ".")
    remu.append("Le Salarié bénéficie de la prime d'ancienneté prévue par la convention collective. Sa rémunération "
                "est soumise aux cotisations sociales (CNPS, CMU) et à l'impôt sur les traitements et salaires, "
                "retenus à la source. Le salaire est payé "
                + ("chaque mois" if mode == "mensuel" else "à la fin de chaque période de travail convenue")
                + (f" par {e(s['mode_paiement'])}" if s.get("mode_paiement") else "") + ".")
    article("Rémunération", *remu)
    article("Congés payés",
            "Le Salarié a droit à un congé payé de 2,2 jours ouvrables par mois de service effectif, dans les "
            "conditions prévues par le Code du travail et la convention collective.")
    article("Obligations du Salarié",
            "Le Salarié s'engage à exécuter avec soin et loyauté les tâches qui lui sont confiées, à respecter le "
            "règlement intérieur, les consignes d'hygiène et de sécurité, et à observer la plus grande discrétion sur "
            "les informations dont il aura connaissance dans l'exercice de ses fonctions.")
    if type_ == "CDI":
        fin = ("Chacune des parties peut mettre fin au présent contrat dans les conditions prévues par le Code du "
               "travail et la convention collective, sous réserve du respect du préavis, sauf faute lourde.")
    elif type_ == "CDD":
        fin = ("Avant son terme, le présent contrat ne peut être rompu qu'en cas de faute lourde, de force majeure "
               "ou d'accord des parties constaté par écrit. À son échéance, et sauf poursuite de la relation de "
               "travail en contrat à durée indéterminée, le Salarié perçoit une indemnité de fin de contrat égale à "
               "3 % du montant total des salaires bruts perçus pendant la durée du contrat.")
    else:
        fin = "L'engagement peut prendre fin à l'issue de chaque journée de travail, sans préavis ni indemnité."
    article("Fin du contrat", fin)
    article("Litiges",
            "Tout différend relatif à l'exécution ou à la rupture du présent contrat sera soumis à la tentative de "
            "conciliation de l'Inspection du travail, puis, à défaut d'accord, au tribunal du travail compétent.")

    av = ""
    if avenants:
        rows = "".join(f"<tr><td>{date_fr(a['date_effet'])}</td><td>{e(a['objet'])}</td><td>"
                       + "; ".join(f"{e(k)} : {fcfa(v) if isinstance(v, (int, float)) else e(v)}"
                                   for k, v in a["modifications"].items() if k != "primes_fixes")
                       + "</td></tr>" for a in avenants)
        av = f"<h2>Avenants</h2><table><tr><th>Date d'effet</th><th>Objet</th><th>Modifications</th></tr>{rows}</table>"

    ville = e(ent.get("ville") or "……………")
    return f"""<html><body>
<h1>{TITRES.get(type_, 'CONTRAT DE TRAVAIL')}</h1>
<p></p>
<p><b>Entre les soussignés :</b></p>
<p>{societe}{', représentée par ' + representant if representant else ''}, ci-après dénommée « l'Employeur »,</p>
<p class="c">d'une part,</p>
<p>et {salarie}, ci-après dénommé(e) « le Salarié »,</p>
<p class="c">d'autre part,</p>
<p>il a été convenu et arrêté ce qui suit :</p>
{''.join(art)}
{av}
<p></p>
<p>Fait à {ville}, le {date_fr(c.get('date_signature') or c['date_debut'])}, en deux exemplaires originaux.</p>
<p></p>
<table><tr><th width="50%">L'Employeur <span class="petit">(signature et cachet)</span></th>
<th width="50%">Le Salarié <span class="petit">(« lu et approuvé »)</span></th></tr>
<tr><td>&#160;<br>&#160;<br>&#160;<br>&#160;</td><td>&#160;</td></tr></table>
</body></html>"""


def contrat_pdf(c: dict, s: dict, ent: dict, avenants: list[dict] | None = None) -> bytes:
    return html_vers_pdf(contrat_html(c, s, ent, avenants))


# ---------------------------------------------------------------------------- livre de paie
def livre_xlsx(per: dict, ent: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    p = per["periode"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Livre de paie"
    ws.append([f"{ent.get('raison_sociale') or 'Entreprise'} — Livre de paie — {libelle_periode(p['annee'], p['mois'])}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    cols = [("Matricule", "matricule"), ("Nom et prénoms", "nom"), ("Emploi", "poste"), ("Contrat", "type"),
            ("Salaire brut", "brut"), ("Brut imposable", "brut_imposable"), ("CNPS salarié", "cnps_salarie"),
            ("CMU salarié", "cmu_salarie"), ("ITS", "its"), ("Autres retenues", "total_retenues"),
            ("Net à payer", "net_a_payer"), ("CNPS retraite pat.", "CNPS_RET"), ("Prest. familiales", "CNPS_PF"),
            ("Maternité", "CNPS_MAT"), ("Accident du travail", "CNPS_AT"), ("CMU pat.", "CMU"),
            ("Impôt patronal", "IS_PAT"), ("FDFP apprentissage", "FDFP_TA"), ("FDFP formation", "FDFP_FPC"),
            ("Charges patronales", "charges_patronales"), ("Coût employeur", "cout_employeur")]
    ws.append([c[0] for c in cols])
    entete = ws.max_row
    for cell in ws[entete]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DCE6F1")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for b in per["bulletins"]:
        r = b["resultat"]
        ligne = []
        for _, k in cols:
            if k in ("matricule", "nom", "poste", "type"):
                ligne.append(b[k])
            elif k in r:
                ligne.append(r[k])
            else:
                ligne.append(r["detail_patronal"].get(k, 0))
        ws.append(ligne)
    n = ws.max_row
    ws.append(["TOTAL", "", "", ""] + [f"=SUM({get_column_letter(i)}{entete + 1}:{get_column_letter(i)}{n})"
                                       for i in range(5, len(cols) + 1)])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for row in ws.iter_rows(min_row=entete + 1, min_col=5):
        for cell in row:
            cell.number_format = "#,##0"
    for i, w in enumerate([11, 28, 22, 10] + [14] * (len(cols) - 4), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=entete + 1, column=3)

    # --- récapitulatif des déclarations
    d = wb.create_sheet("Déclarations")
    tot = {}
    for b in per["bulletins"]:
        r = b["resultat"]
        for k, v in r["detail_patronal"].items():
            tot[k] = tot.get(k, 0) + v
        for k in ("cnps_salarie", "cmu_salarie", "its", "brut", "brut_imposable", "net_a_payer"):
            tot[k] = tot.get(k, 0) + r[k]
    d.append([f"Récapitulatif des déclarations — {libelle_periode(p['annee'], p['mois'])}"])
    d["A1"].font = Font(bold=True, size=13)
    d.append([])
    rows = [
        ("Effectif", len(per["bulletins"]), ""),
        ("Masse salariale brute", tot.get("brut", 0), ""),
        ("Masse salariale imposable", tot.get("brut_imposable", 0), ""),
        ("", "", ""),
        ("CNPS — retraite (part salariale)", tot.get("cnps_salarie", 0), "CNPS"),
        ("CNPS — retraite (part patronale)", tot.get("CNPS_RET", 0), "CNPS"),
        ("CNPS — prestations familiales", tot.get("CNPS_PF", 0), "CNPS"),
        ("CNPS — assurance maternité", tot.get("CNPS_MAT", 0), "CNPS"),
        ("CNPS — accident du travail", tot.get("CNPS_AT", 0), "CNPS"),
        ("Total à verser à la CNPS", sum(tot.get(k, 0) for k in ("cnps_salarie", "CNPS_RET", "CNPS_PF",
                                                                  "CNPS_MAT", "CNPS_AT")), "CNPS"),
        ("", "", ""),
        ("CMU (part salariale)", tot.get("cmu_salarie", 0), "CNAM"),
        ("CMU (part patronale)", tot.get("CMU", 0), "CNAM"),
        ("", "", ""),
        ("ITS retenu sur salaires", tot.get("its", 0), "DGI"),
        ("Impôt sur salaires — part patronale", tot.get("IS_PAT", 0), "DGI"),
        ("FDFP — taxe d'apprentissage", tot.get("FDFP_TA", 0), "DGI / FDFP"),
        ("FDFP — formation professionnelle continue", tot.get("FDFP_FPC", 0), "DGI / FDFP"),
        ("", "", ""),
        ("Net à payer aux salariés", tot.get("net_a_payer", 0), ""),
    ]
    d.append(["Rubrique", "Montant (FCFA)", "Organisme"])
    for cell in d[d.max_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DCE6F1")
    for row in rows:
        d.append(list(row))
        d.cell(row=d.max_row, column=2).number_format = "#,##0"
        if row[0].startswith("Total"):
            for cell in d[d.max_row]:
                cell.font = Font(bold=True)
    d.column_dimensions["A"].width = 44
    d.column_dimensions["B"].width = 18
    d.column_dimensions["C"].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
