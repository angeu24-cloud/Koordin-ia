"""Note de calcul (HTML + PDF) et métré (béton, acier)."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from ..codes.common import bar_mass
from ..design import ProjectResult


def _f(v: float, n: int = 1) -> str:
    return f"{v:,.{n}f}".replace(",", " ").replace(".", ",")


def quantities(res: ProjectResult) -> dict:
    """Métré estimatif : béton (m³) et acier (kg) par famille d'éléments."""
    proj = res.project
    cover = res.code.cover
    q = {"poteaux": [0.0, 0.0], "poutres": [0.0, 0.0], "semelles": [0.0, 0.0]}
    for r in res.columns:
        d = r.design
        H = proj.storeys[r.storey - 1].height
        q["poteaux"][0] += d.b * d.h * H
        if d.bars:
            lap = 40 * d.bars.d / 1000
            q["poteaux"][1] += d.bars.n * (H + lap) * bar_mass(d.bars.d)
        if d.stirrups:
            per = 2 * (d.b + d.h - 4 * cover) + 0.20
            q["poteaux"][1] += (int(H / d.stirrups.s) + 1) * per * bar_mass(d.stirrups.d)
    for r in res.beams:
        d = r.design
        n_lvl = max(1, proj.n - 1) if (proj.single_plan and r.level == "courant") else 1
        L = r.span
        q["poutres"][0] += n_lvl * d.b * d.h * L
        kg = 0.0
        for bars in (d.bars_bottom, d.bars_top):
            if bars:
                kg += bars.n * (L + 2 * 40 * bars.d / 1000) * bar_mass(bars.d)
        if d.stirrups:
            per = 2 * (d.b + d.h - 4 * cover) + 0.20
            kg += (int(L / d.stirrups.s) + 1) * per * bar_mass(d.stirrups.d)
        q["poutres"][1] += n_lvl * kg
    for f in res.footings:
        d = f.design
        q["semelles"][0] += d.A * d.B * d.h
        for bars, length in ((d.bars_x, d.A), (d.bars_y, d.B)):
            if bars:
                q["semelles"][1] += bars.n * (length - 0.10 + 0.30) * bar_mass(bars.d)
    return {k: {"beton_m3": round(v[0], 2), "acier_kg": round(v[1], 0)} for k, v in q.items()}


CSS = """
body { font-family: sans-serif; font-size: 9pt; color: #111; }
h1 { font-size: 16pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 14pt; border-bottom: 1px solid #444; }
h3 { font-size: 10pt; margin-top: 8pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0; }
th, td { border: 1px solid #888; padding: 2pt 3pt; text-align: center; font-size: 8pt; }
th { background-color: #ddd; }
.ko { color: #b00; font-weight: bold; }
.warn { color: #8a5a00; }
.small { font-size: 7.5pt; color: #444; }
"""


def build_html(res: ProjectResult) -> str:
    b, ls, code, td = res.building, res.loads, res.code, res.takedown
    proj = res.project
    e = html.escape
    out: list[str] = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    out.append("<h1>Note de calcul — Structure béton armé</h1>")
    if proj.name:
        out.append(f"<h2 style='border:none;margin-top:2pt'>{e(proj.name)}</h2>")
    out.append(f"<p class='small'>Koordin-IA — {date.today():%d/%m/%Y} — Source : {e(proj.source)}</p>")
    out.append(
        "<p class='warn'><b>Avertissement :</b> document généré automatiquement à partir d'un modèle "
        "reconnu sur plan. Il constitue une aide au pré-dimensionnement et doit être vérifié, complété "
        "et visé par un ingénieur structure qualifié avant toute exécution.</p>"
    )

    out.append("<h2>1. Hypothèses</h2><ul>")
    out.append(f"<li>Règlement : <b>{e(code.name)}</b></li>")
    for line in code.describe():
        out.append(f"<li>{e(line)}</li>")
    if proj.single_plan:
        out.append(f"<li>Bâtiment : {proj.n} niveau(x), hauteur d'étage {_f(proj.storeys[0].height, 2)} m ; "
                   f"longueur de flambement lf = 0,7·l0 = {_f(0.7 * proj.storeys[0].height, 2)} m</li>")
    else:
        out.append(f"<li>Bâtiment : {proj.n} étages ({', '.join(st.name for st in proj.storeys)}) + terrasse ; "
                   "longueur de flambement lf = 0,7·l0</li>")
    out.append(f"<li>Plancher : {'corps creux (porteur dans un sens)' if ls.floor_type == 'corps_creux' else 'dalle pleine'}</li>")
    out.append(f"<li>Contrainte admissible du sol (ELS) : σsol = {_f(res.sigma_sol, 2)} MPa</li></ul>")

    out.append("<h2>2. Charges surfaciques</h2><table><tr><th>Niveau</th><th>G (kN/m²)</th><th>Q (kN/m²)</th>"
               "<th>Détail G</th></tr>")
    out.append(f"<tr><td>Étage courant</td><td>{_f(td.surface_g_floor, 2)}</td><td>{_f(td.surface_q_floor, 2)}</td>"
               f"<td>plancher {_f(ls.g_floor, 2)} + revêtements/cloisons {_f(ls.g_finishes, 2)}</td></tr>")
    out.append(f"<tr><td>Terrasse</td><td>{_f(td.surface_g_roof, 2)}</td><td>{_f(td.surface_q_roof, 2)}</td>"
               f"<td>plancher {_f(ls.g_floor, 2)} + étanchéité/forme de pente {_f(ls.g_roof_extra, 2)}</td></tr>"
               "</table>")
    out.append("<p class='small'>Poids propre du béton armé : 25 kN/m³. "
               + ("Dégression des charges d'exploitation : NF P06-001. " if ls.degression else "")
               + ("Majoration des réactions : +15 % (2 travées) / +10 % (≥ 3 travées) sur appuis voisins de rive."
                  if ls.continuity else "") + "</p>")

    out.append("<h2>3. Modèle structurel reconnu</h2>")
    if not proj.single_plan:
        out.append("<table><tr><th>Étage</th><th>Hauteur (m)</th><th>Planche</th><th>Poteaux</th><th>Poutres</th>"
                   "<th>Plancher porté</th><th>Surface (m²)</th></tr>")
        for k, st in enumerate(proj.storeys):
            sl = td.storeys[k]
            out.append(f"<tr><td>{e(st.name)}</td><td>{_f(st.height, 2)}</td><td>{e(st.sheet)}</td>"
                       f"<td>{len(st.plan.columns)}</td><td>{len(st.plan.beams)}</td><td>{e(sl.floor_name)}</td>"
                       f"<td>{_f(sl.slab_area, 1)}</td></tr>")
        out.append("</table>")
        if td.wall_supports:
            out.append("<h3>Poteaux reposant sur des murs</h3><table><tr><th>Poteau</th><th>Mur de l'étage</th>"
                       "<th>G (kN)</th><th>Q (kN)</th></tr>")
            for ws in td.wall_supports:
                out.append(f"<tr><td>{ws.column_id}</td><td>{e(proj.storeys[ws.storey - 1].name)}</td>"
                           f"<td>{_f(ws.g)}</td><td>{_f(ws.q)}</td></tr>")
            out.append("</table>")
    direct = sum(td.column_direct_area.values())
    out.append(f"<p>{len(b.columns)} poteaux, {len(b.beams)} poutres. Surface de plancher par niveau : "
               f"<b>{_f(td.slab_area, 1)} m²</b> (dont {_f(direct, 1)} m² reportés directement sur poteaux). "
               f"Trame X : {' / '.join(_f(v, 2) for v in b.grid_x)} m — "
               f"Trame Y : {' / '.join(_f(v, 2) for v in b.grid_y)} m.</p>")
    if res.warnings:
        out.append("<h3>Remarques et points à vérifier</h3><ul>")
        for w in dict.fromkeys(res.warnings):
            out.append(f"<li class='warn'>{e(w)}</li>")
        out.append("</ul>")

    out.append("<h2>4. Descente de charges sur poteaux</h2>")
    out.append("<table><tr><th>Poteau</th><th>Niveau</th><th>G cumulé (kN)</th><th>Q cumulé (kN)</th>"
               "<th>Nser = G+Q (kN)</th><th>Nu = 1,35G+1,5Q (kN)</th></tr>")
    for r in sorted(res.columns, key=lambda r: (int(r.column_id[1:]), -r.storey)):
        out.append(f"<tr><td>{r.column_id}</td><td>{e(r.storey_name or str(r.storey))}</td><td>{_f(r.g)}</td><td>{_f(r.q)}</td>"
                   f"<td>{_f(r.nser)}</td><td>{_f(r.nu)}</td></tr>")
    out.append("</table>")

    out.append("<h2>5. Dimensionnement des poteaux</h2>")
    out.append("<table><tr><th>Poteau</th><th>Niv.</th><th>Section (cm)</th><th>λ</th><th>Nu (kN)</th>"
               "<th>A calc. (cm²)</th><th>A min (cm²)</th><th>Armatures</th><th>Transversales</th><th>État</th></tr>")
    for r in sorted(res.columns, key=lambda r: (int(r.column_id[1:]), -r.storey)):
        d = r.design
        state = "OK" if d.ok else f"<span class='ko'>NON — {e('; '.join(d.notes))}</span>"
        out.append(f"<tr><td>{r.column_id}</td><td>{e(r.storey_name or str(r.storey))}</td><td>{d.b * 100:.0f}×{d.h * 100:.0f}"
                   f"{' *' if r.resized else ''}</td><td>{_f(d.slenderness)}</td><td>{_f(d.nu)}</td>"
                   f"<td>{_f(d.as_req, 2)}</td><td>{_f(d.as_min, 2)}</td><td>{d.bars or '—'}</td>"
                   f"<td>{d.stirrups or '—'}</td><td>{state}</td></tr>")
    out.append("</table><p class='small'>* section augmentée automatiquement par rapport au plan.</p>")

    out.append("<h2>6. Dimensionnement des poutres</h2>")
    out.append("<table><tr><th>Poutre</th><th>Niveau</th><th>Section (cm)</th><th>L (m)</th><th>pu (kN/m)</th>"
               "<th>M0 (kN.m)</th><th>Mt (kN.m)</th><th>Ma (kN.m)</th><th>Vu (kN)</th><th>A trav. (cm²)</th>"
               "<th>Inf.</th><th>A app. (cm²)</th><th>Sup.</th><th>Cadres</th><th>État</th></tr>")
    for r in res.beams:
        d = r.design
        state = "OK" if d.ok and not d.notes else (
            "OK*" if d.ok else f"<span class='ko'>NON</span>")
        out.append(f"<tr><td>{r.beam_id}</td><td>{r.level}</td><td>{d.b * 100:.0f}×{d.h * 100:.0f}</td>"
                   f"<td>{_f(r.span, 2)}</td><td>{_f(r.pu_m)}</td><td>{_f(r.m0)}</td><td>{_f(d.mu_span)}</td>"
                   f"<td>{_f(d.mu_support)}</td><td>{_f(d.vu)}</td><td>{_f(d.as_span, 2)}</td>"
                   f"<td>{d.bars_bottom or '—'}</td><td>{_f(d.as_support, 2)}</td><td>{d.bars_top or '—'}</td>"
                   f"<td>{d.stirrups or '—'}</td><td>{state}</td></tr>")
    out.append("</table>")
    notes = [(r.beam_id, r.level, n) for r in res.beams for n in r.design.notes]
    if notes:
        out.append("<ul>" + "".join(f"<li class='warn'>{i} ({lv}) : {e(n)}</li>" for i, lv, n in notes) + "</ul>")
    out.append("<p class='small'>Moments : méthode forfaitaire simplifiée — Mt = 0,85·M0 (travée de rive) / "
               "0,75·M0 (intermédiaire) ; Ma = 0,2·M0 (rive), 0,6·M0 (2 travées), 0,5/0,4·M0 (≥ 3 travées).</p>")

    out.append("<h2>7. Fondations — semelles isolées</h2>")
    out.append("<table><tr><th>Poteau</th><th>A×B×h (cm)</th><th>Nser (kN)</th><th>Nu (kN)</th><th>σ (MPa)</th>"
               "<th>Ax (cm²)</th><th>// A</th><th>Ay (cm²)</th><th>// B</th><th>État</th></tr>")
    for f in res.footings:
        d = f.design
        sig = d.nser / (d.A * d.B) / 1000
        out.append(f"<tr><td>{f.column_id}</td><td>{d.A * 100:.0f}×{d.B * 100:.0f}×{d.h * 100:.0f}</td>"
                   f"<td>{_f(d.nser)}</td><td>{_f(d.nu)}</td><td>{_f(sig, 3)}</td><td>{_f(d.as_x, 2)}</td>"
                   f"<td>{d.bars_x}</td><td>{_f(d.as_y, 2)}</td><td>{d.bars_y}</td>"
                   f"<td>{'OK' if d.ok else '<span class=ko>NON</span>'}</td></tr>")
    out.append("</table><p class='small'>Méthode des bielles : d ≥ (A − a)/4 ; A_x = Nu·(A − a)/(8·d·fsu). "
               "Poids propre de la semelle inclus.</p>")

    out.append("<h2>8. Métré estimatif</h2><table><tr><th>Élément</th><th>Béton (m³)</th><th>Acier (kg)</th>"
               "<th>Ratio (kg/m³)</th></tr>")
    tot_c = tot_s = 0.0
    for k, v in quantities(res).items():
        tot_c += v["beton_m3"]
        tot_s += v["acier_kg"]
        ratio = v["acier_kg"] / v["beton_m3"] if v["beton_m3"] else 0
        out.append(f"<tr><td>{k.capitalize()}</td><td>{_f(v['beton_m3'], 2)}</td><td>{_f(v['acier_kg'], 0)}</td>"
                   f"<td>{_f(ratio, 0)}</td></tr>")
    out.append(f"<tr><th>Total</th><th>{_f(tot_c, 2)}</th><th>{_f(tot_s, 0)}</th><th></th></tr></table>")
    out.append("<p class='small'>Hors planchers (dalles / poutrelles), longrines et chaînages.</p>")
    out.append("</body></html>")
    return "\n".join(out)


def write_report(res: ProjectResult, folder: Path) -> tuple[Path, Path]:
    import pymupdf

    html_doc = build_html(res)
    html_path = folder / "note_de_calcul.html"
    html_path.write_text(html_doc, encoding="utf-8")
    pdf_path = folder / "note_de_calcul.pdf"
    story = pymupdf.Story(html=html_doc)
    writer = pymupdf.DocumentWriter(str(pdf_path))
    mediabox = pymupdf.paper_rect("a4-l")
    where = mediabox + (36, 36, -36, -36)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return html_path, pdf_path
