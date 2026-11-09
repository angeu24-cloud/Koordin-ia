"""Note de calcul (HTML + PDF) et métré (béton, acier)."""
from __future__ import annotations

import html
import re
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


def build_html(res: ProjectResult, mep=None) -> str:
    b, ls, code, td = res.building, res.loads, res.code, res.takedown
    proj = res.project
    e = html.escape
    out: list[str] = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    out.append("<h1>Note de calcul — Structure béton armé</h1>")
    if proj.name:
        out.append(f"<h2 style='border:none;margin-top:2pt'>{e(proj.name)}</h2>")
    out.append(f"<p class='small'>BatiCalc — {date.today():%d/%m/%Y} — Source : {e(proj.source)}</p>")
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
    ftxt = {"corps_creux": "corps creux (porteur dans un sens)", "dalle_pleine": "dalle pleine",
            "charpente": "toiture légère : charpente bois et couverture tôle sur chaînages (répartition sur tous les murs)"}
    out.append(f"<li>Plancher haut : {ftxt.get(ls.floor_type, ls.floor_type)}</li>")
    if ls.roof_type and ls.roof_type != ls.floor_type:
        out.append(f"<li>Toiture (dernier niveau) : {ftxt.get(ls.roof_type, 'dalle en terrasse')} — "
                   f"G = {ls.g_roof_extra:.2f} kN/m², Q = {ls.q_roof:.2f} kN/m²</li>")
    if ls.ground_wall_load:
        out.append(f"<li>Maçonnerie du rez-de-chaussée portée par des longrines {ls.longrine_b * 100:.0f}×"
                   f"{ls.longrine_h * 100:.0f} : {ls.ground_wall_load:.2f} kN/m</li>")
    out.append(f"<li>Contrainte admissible du sol (ELS) : σsol = {_f(res.sigma_sol, 3)} MPa"
               f"{' (rapport géotechnique)' if res.geotech and res.geotech.sigma_sol == res.sigma_sol else ''}</li></ul>")
    geo = res.geotech
    if geo:
        from ..geotech import summary_lines

        banner = ("" if geo.valide else "<p class='ko'>Valeurs extraites automatiquement du rapport et NON VALIDÉES "
                  "par l'ingénieur.</p>")
        out.append(f"<h3>Données géotechniques</h3>{banner}<p class='small'>Source : {e(geo.fichier)}</p>"
                   "<table><tr><th>Donnée</th><th>Valeur</th><th>Extrait du rapport</th></tr>")
        for k, v, src in summary_lines(geo):
            if v != "—":
                out.append(f"<tr><td>{e(k)}</td><td>{e(v)}</td><td class='small'>{e(src)}</td></tr>")
        out.append("</table>")
        for r in geo.remarques:
            out.append(f"<p class='warn'>{e(r)}</p>")

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

    # --- Locaux, usages et trémies
    rows_done: set = set()
    loc_html: list[str] = []
    for sl in td.storeys:
        plan = proj.storeys[sl.index].plan
        key = (id(plan), sl.roof)
        if key in rows_done or (proj.single_plan and not sl.roof and sl.index != proj.n - 2):
            continue
        rows_done.add(key)
        openings = [z for z in (plan.zones or []) if z["type"] == "ouverture"]
        if not sl.zones and not openings:
            continue
        floor = ("Étage courant" if not sl.roof else "Terrasse") if proj.single_plan else sl.floor_name
        loc_html.append(f"<h3>{e(floor)}</h3><table><tr><th>Local</th><th>Usage retenu</th><th>Surface (m²)</th>"
                        "<th>Surface écrite (m²)</th><th>G (kN/m²)</th><th>Q (kN/m²)</th><th>Remarque</th></tr>")
        for z, area, g, q in sl.zones:
            rem = "contour approché" if z.approx else ""
            if z.note:
                rem = (rem + " ; " if rem else "") + z.note
            loc_html.append(f"<tr><td>{e(z.name)}</td><td>{e(z.usage)}</td><td>{_f(area, 1)}</td>"
                            f"<td>{_f(z.area_label, 2) if z.area_label else '—'}</td><td>{_f(g, 2)}</td>"
                            f"<td>{_f(q, 2)}</td><td class='small'>{e(rem)}</td></tr>")
        for z in openings:
            loc_html.append(f"<tr><td>{e(z['name'])}</td><td>{e(z['usage'])}</td><td>{_f(z['area'], 1)}</td>"
                            f"<td>{_f(z['area_label'], 2) if z['area_label'] else '—'}</td><td>—</td><td>—</td>"
                            "<td class='small'>trémie : retirée du plancher</td></tr>")
        loc_html.append("</table>")
    if loc_html:
        out.append("<h2>3 bis. Locaux, usages et trémies</h2>")
        out.append(f"<p class='small'>Locaux lus sur les étiquettes du plan et délimités jusqu'aux murs ; charges "
                   f"d'après le catalogue d'usages (NF P06-001). Hors locaux : G = {_f(td.surface_g_floor, 2)}, "
                   f"Q = {_f(td.surface_q_floor, 2)} kN/m².</p>")
        out += loc_html
    if res.balconies:
        out.append("<h3>Balcons en console (par mètre linéaire)</h3><table><tr><th>Plancher</th><th>Balcon</th>"
                   "<th>Surface (m²)</th><th>Porte-à-faux (m)</th><th>Épaisseur (cm)</th><th>G (kN/m²)</th>"
                   "<th>Q (kN/m²)</th><th>Mu (kN.m/m)</th><th>A sup. (cm²/m)</th><th>Chapeaux</th>"
                   "<th>Répartition</th><th>Remarque</th></tr>")
        for bz in res.balconies:
            out.append(f"<tr><td>{e(bz.floor)}</td><td>{e(bz.name)}</td><td>{_f(bz.area, 1)}</td>"
                       f"<td>{_f(bz.length, 2)}</td><td>{bz.h * 100:.0f}</td><td>{_f(bz.g, 2)}</td>"
                       f"<td>{_f(bz.q, 2)}</td><td>{_f(bz.mu, 1)}</td><td>{_f(bz.as_top, 2)}</td><td>{bz.bars_top}</td>"
                       f"<td>{bz.bars_dist}</td><td class='small'>{e('; '.join(bz.notes))}</td></tr>")
        out.append("</table><p class='small'>Console encastrée : charges réparties + garde-corps 1 kN/m en bout "
                   "et effort horizontal 1 kN/m à 1 m ; épaisseur h ≥ L/10 (15 cm mini).</p>")

    if res.transfers:
        out.append("<h3>Poutres de transfert créées automatiquement</h3>"
                   "<table><tr><th>Poutre</th><th>Plancher</th><th>Appuis</th><th>Portée (m)</th>"
                   "<th>Poteaux portés</th><th>Mu (kN.m)</th><th>Vu (kN)</th><th>Section (cm)</th><th>Inf.</th>"
                   "<th>Sup.</th><th>Cadres</th><th>État</th></tr>")
        for t in res.transfers:
            d = t.design
            out.append(f"<tr><td>{t.beam_id}</td><td>{e(t.floor)}</td><td>{e(t.supports)}</td>"
                       f"<td>{_f(t.length, 2)}</td><td>{e(', '.join(t.carried))}</td><td>{_f(t.m0)}</td>"
                       f"<td>{_f(t.vu)}</td><td>{d.b * 100:.0f}×{d.h * 100:.0f}</td><td>{d.bars_bottom or '—'}</td>"
                       f"<td>{d.bars_top or '—'}</td><td>{d.stirrups or '—'}</td>"
                       f"<td>{'OK' if d.ok else '<span class=ko>NON</span>'}</td></tr>")
        out.append("</table><p class='small'>Poutres isostatiques sous charges ponctuelles des poteaux "
                   "naissants + poids propre ; appuis = poteaux ou murs de l'étage inférieur. À valider "
                   "par l'ingénieur (nœuds, flèche, ferraillage des appuis).</p>")

    if res.stairs:
        out.append("<h3>Escaliers</h3><table><tr><th>Volée</th><th>Cage (m)</th><th>Marches</th><th>h × g (cm)</th>"
                   "<th>Volées × emm. (m)</th><th>Portée (m)</th><th>Paillasse (cm)</th><th>G volée / palier "
                   "(kN/m²)</th><th>M0 (kN.m/m)</th><th>Aciers inf.</th><th>Chapeaux</th><th>Répartition</th>"
                   "<th>Poutre palière (kN/m ELU)</th><th>Remarque</th></tr>")
        for st in res.stairs:
            out.append(f"<tr><td>{e(st.floor)}</td><td>{_f(st.cage[0], 2)} × {_f(st.cage[1], 2)}</td>"
                       f"<td>{st.risers}</td><td>{st.riser_h * 100:.1f} × {st.going * 100:.0f}</td>"
                       f"<td>{st.flights} × {_f(st.width, 2)}</td><td>{_f(st.span, 2)}</td>"
                       f"<td>{st.thickness * 100:.0f}</td><td>{_f(st.g_flight, 2)} / {_f(st.g_landing, 2)}</td>"
                       f"<td>{_f(st.m0)}</td><td>{st.bars_bottom}</td><td>{st.bars_top}</td><td>{st.bars_dist}</td>"
                       f"<td>{_f(st.landing_beam_load)}</td><td class='small'>{e('; '.join(st.notes))}</td></tr>")
        out.append("</table><p class='small'>Paillasse + palier en travée unique sur poutres palières, "
                   "Mt = 0,85·M0, Ma = 0,30·M0 ; marches 2h + g ≈ 63 cm ; Q = 2,5 kN/m².</p>")

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

    if res.longrines:
        out.append("<h2>6 bis. Longrines (maçonnerie du rez-de-chaussée)</h2>")
        out.append("<table><tr><th>Longrine</th><th>Section (cm)</th><th>L (m)</th><th>pu (kN/m)</th><th>M0 (kN.m)</th>"
                   "<th>A trav. (cm²)</th><th>Inf.</th><th>A app. (cm²)</th><th>Sup.</th><th>Cadres</th><th>État</th></tr>")
        for r in res.longrines:
            d = r.design
            out.append(f"<tr><td>{r.beam_id}</td><td>{d.b * 100:.0f}×{d.h * 100:.0f}</td><td>{_f(r.span, 2)}</td>"
                       f"<td>{_f(r.pu_m)}</td><td>{_f(r.m0)}</td><td>{_f(d.as_span, 2)}</td><td>{d.bars_bottom or '—'}</td>"
                       f"<td>{_f(d.as_support, 2)}</td><td>{d.bars_top or '—'}</td><td>{d.stirrups or '—'}</td>"
                       f"<td>{'OK' if d.ok else '<span class=ko>NON</span>'}</td></tr>")
        out.append("</table><p class='small'>Charge : maçonnerie + poids propre ; Mt = 0,8·M0, Ma = 0,5·M0 ; réactions "
                   "ajoutées aux charges des semelles.</p>")

    if res.foundation_type == "pieux":
        out.append("<h2>7. Fondations profondes — charges en tête de pieux</h2>")
        out.append("<table><tr><th>Appui</th><th>Nser (kN)</th><th>Nu (kN)</th><th>Nombre de pieux</th></tr>")
        for p_ in res.piles:
            out.append(f"<tr><td>{p_['poteau']}{' (mur)' if p_['sous_mur'] else ''}</td><td>{_f(p_['nser'])}</td>"
                       f"<td>{_f(p_['nu'])}</td><td>{p_['n_pieux'] or 'à préciser'}</td></tr>")
        out.append("</table>")
    if res.raft:
        r_ = res.raft
        out.append("<h2>7. Fondations — radier général</h2>")
        out.append(f"<p>Aire {_f(r_['aire'], 1)} m² ; épaisseur {r_['epaisseur'] * 100:.0f} cm (portée {_f(r_['portee'], 2)} m "
                   f"/ 20 et poinçonnement) ; contrainte moyenne ELS {_f(r_['sigma'], 3)} MPa "
                   f"({'OK' if r_['ok'] else '<span class=ko>NON</span>'} ≤ {_f(res.sigma_sol, 3)}) ; "
                   f"moment {_f(r_['mu'])} kN.m/m ; aciers {_f(r_['as'], 2)} cm²/m ({r_['aciers']}) "
                   "par face et par direction.</p>")
    out.append("<h2>7. Fondations — semelles isolées</h2>" if res.footings else "")
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
    if mep is not None:
        out += mep_html(mep)
    out.append("</body></html>")
    return "\n".join(out)


def mep_html(mep) -> list[str]:
    """Section « Réseaux » : électricité (NF C 15-100), climatisation, plomberie (DTU 60.11)."""
    e = html.escape
    out = ["<h2>9. Réseaux — électricité</h2>",
           "<p class='small'>Éclairage : n = E·S / (Φ·η) avec η = facteur d'utilisation × maintenance ; prises et "
           "circuits selon NF C 15-100 (éclairage 1,5 mm² / 16 A, prises 2,5 mm² / 20 A, différentiels 30 mA) ; "
           "câble TGBT → TD choisi pour Iz ≥ 1,25·Ib et ΔU ≤ 3 %.</p>",
           "<table><tr><th>Niveau</th><th>Local</th><th>Usage</th><th>S (m²)</th><th>Luminaires</th>"
           "<th>Type</th><th>Prises</th><th>Interr.</th></tr>"]
    for s in mep.storeys:
        for r in s.rooms:
            out.append(f"<tr><td>{e(s.name)}</td><td>{e(r['local'])}</td><td>{e(r['usage'])}</td>"
                       f"<td>{_f(r['surface'])}</td><td>{r['luminaires']}</td><td>{e(r['type_luminaire'])}</td>"
                       f"<td>{r['prises']}</td><td>{r['interrupteurs']}</td></tr>")
    out.append("</table><table><tr><th>Tableau</th><th>Circuits écl. / prises / clim</th><th>P (kW)</th>"
               "<th>Ib (A)</th><th>Câble</th><th>L (m)</th><th>ΔU (%)</th></tr>")
    for s in mep.storeys:
        c, f = s.circuits, s.feeder
        out.append(f"<tr><td>TD {e(s.name)}</td><td>{c.get('eclairage', 0)} / {c.get('prises', 0)} / "
                   f"{c.get('clim', 0)}</td><td>{_f(s.power_kw)}</td><td>{_f(s.current_a)}</td>"
                   f"<td>{f.get('section_mm2', '')} mm²</td><td>{_f(f.get('longueur_m', 0))}</td>"
                   f"<td>{_f(f.get('chute_tension', 0), 2)}</td></tr>")
    t = mep.tgbt
    out.append(f"<tr><th>TGBT</th><th></th><th>{_f(t.get('puissance_kw', 0))}</th><th>{_f(t.get('courant_a', 0))}</th>"
               f"<th colspan=3>{_f(t.get('puissance_kva', 0))} kVA</th></tr></table>")
    out.append("<h2>10. Réseaux — climatisation</h2><p class='small'>Bilan simplifié : apports surfaciques par "
               "usage + apports solaires des vitrages en façade ; splits muraux choisis dans la gamme courante.</p>"
               "<table><tr><th>Niveau</th><th>Local</th><th>Apports (kW)</th><th>Unités</th></tr>")
    for s in mep.storeys:
        for r in s.rooms:
            if r["splits"]:
                out.append(f"<tr><td>{e(s.name)}</td><td>{e(r['local'])}</td><td>{_f(r['apports_kw'], 2)}</td>"
                           f"<td>{e(', '.join(r['splits']))}</td></tr>")
        out.append(f"<tr><th>{e(s.name)}</th><th>Total</th><th>{_f(s.cool_kw)}</th><th>{len(s.units)} unités</th></tr>")
    out.append("</table>")
    out.append("<h2>11. Réseaux — plomberie sanitaire</h2><p class='small'>DTU 60.11 : débit probable "
               "Qp = y·ΣQb avec y = 0,8/√(n−1) ; diamètres PVC pression pour v ≤ 2 m/s (branches) et "
               "v ≤ 1,5 m/s (colonnes) ; chutes Ø100 avec WC, Ø90 sinon.</p>"
               "<table><tr><th>Colonne</th><th>Tronçon</th><th>Appareils desservis</th><th>Qp (l/s)</th>"
               "<th>Ø EF</th><th>v (m/s)</th><th>Ø chute</th></tr>")
    for col in mep.columns:
        for sg in col.get("segments", []):
            out.append(f"<tr><td>{e(col['id'])}</td><td>{e(sg['niveau'])}</td><td>{sg['appareils']}</td>"
                       f"<td>{_f(sg['debit_probable_ls'], 3)}</td><td>{sg['dn']}</td><td>{_f(sg['vitesse_ms'], 2)}</td>"
                       f"<td>{sg['chute_dn']}</td></tr>")
    out.append("</table>")
    if mep.notes:
        out.append("<ul>" + "".join(f"<li class='small'>{e(n)}</li>" for n in mep.notes) + "</ul>")
    return out


def write_report(res: ProjectResult, folder: Path, mep=None) -> tuple[Path, Path]:
    import pymupdf

    html_doc = build_html(res, mep)
    html_path = folder / "note_de_calcul.html"
    html_path.write_text(html_doc, encoding="utf-8")
    pdf_path = folder / "note_de_calcul.pdf"
    # Mise en page section par section (évite un blocage de PyMuPDF quand un grand tableau
    # commence en bas de page) ; chaque section reprend sous la précédente.
    head = html_doc[:html_doc.index("<body>") + 6]
    body = html_doc[html_doc.index("<body>") + 6:html_doc.rindex("</body>")]
    parts = re.split(r"(?=<h2>)", body)
    writer = pymupdf.DocumentWriter(str(pdf_path))
    mediabox = pymupdf.paper_rect("a4-l")
    full = mediabox + (36, 36, -36, -36)
    dev = writer.begin_page(mediabox)
    y = full.y0
    pages = 1
    for part in parts:
        if not part.strip():
            continue
        story = pymupdf.Story(html=head + part + "</body></html>")
        more, stalled = True, 0
        while more:
            if full.y1 - y < 60:
                writer.end_page()
                dev = writer.begin_page(mediabox)
                pages += 1
                y = full.y0
            where = pymupdf.Rect(full.x0, y, full.x1, full.y1)
            more, filled = story.place(where)
            story.draw(dev)
            fr = pymupdf.Rect(filled)
            if more:
                stalled = stalled + 1 if (fr.is_empty or fr.height < 1) else 0
                writer.end_page()
                dev = writer.begin_page(mediabox)
                pages += 1
                y = full.y0
                if stalled >= 3 or pages >= 400:
                    res.warnings.append("Note PDF incomplète (élément trop grand pour une page) : voir la version HTML.")
                    more = False
            else:
                y = (fr.y1 if not fr.is_empty else y) + 8
    writer.end_page()
    writer.close()
    return html_path, pdf_path
