"""Interface en ligne de commande.

Exemples :
    koordinia exemple -o essai/
    koordinia detecter plan.dwg --niveaux 4 -o projet/
    koordinia calculer plan.pdf --echelle 100 --norme bael --niveaux 4 -o projet/
    koordinia calculer --modele projet/modele.json --norme ec2 -o projet/
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .model import Building, LoadSettings


def _add_import_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("plan", nargs="?", help="Plan d'étage courant : .dwg, .dxf ou .pdf")
    p.add_argument("--echelle", type=int, help="PDF : échelle du plan (100 pour 1/100). Détectée si absente.")
    p.add_argument("--page", type=int, default=1, help="PDF : numéro de page (défaut 1)")
    p.add_argument("--unites", choices=["mm", "cm", "m"], help="DWG/DXF : unités du dessin si non définies")
    p.add_argument("--niveaux", type=int, default=1, help="Nombre de planchers au-dessus des fondations")
    p.add_argument("--hauteur", type=float, default=3.0, help="Hauteur d'étage (m)")
    p.add_argument("--portee-max", type=float, default=8.0, help="Portée maximale d'une poutre (m)")
    p.add_argument("--planche", help="Planche à traiter si le dessin en contient plusieurs : numéro ou mots du "
                                     "titre (ex. « etage courant »). Voir « koordinia planches ».")
    p.add_argument("--calque-poteaux", help="Calque des poteaux (nom exact ou expression régulière)")
    p.add_argument("--sans-contour", action="store_true",
                   help="Ne pas déduire le contour du plancher des murs (mailles de la trame uniquement)")
    p.add_argument("-o", "--sortie", default="resultats", help="Dossier de sortie")


def _import_model(args) -> tuple[Building, object | None]:
    from .importers import import_plan
    from .recognition import build_model

    from .sheets import crop, find_sheets, select_sheet

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page)
    sheets = find_sheets(drawing)
    if args.planche:
        if not sheets:
            raise ValueError("Aucune planche (cadre) détectée dans le dessin : retirez --planche.")
        sheet = select_sheet(sheets, args.planche)
        drawing = crop(drawing, sheet.bbox)
        drawing.warnings.append(f"Planche traitée : n° {sheet.index} « {sheet.title} ».")
    elif sum(s.is_plan for s in sheets) > 1:
        raise ValueError(
            "Le dessin contient plusieurs planches ; choisissez celle de l'étage courant avec --planche :\n"
            + "\n".join(f"  {s.index}. {s.title}" for s in sheets)
        )
    bld = build_model(drawing, n_levels=args.niveaux, floor_height=args.hauteur, max_span=args.portee_max,
                      column_layer=args.calque_poteaux, footprint=not args.sans_contour)
    return bld, drawing


def cmd_detecter(args) -> int:
    from .outputs.drawings import plan_controle

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    bld, drawing = _import_model(args)
    bld.save(out / "modele.json")
    plan_controle(bld, drawing, out / "controle_modele.dxf")
    for w in bld.warnings:
        print("•", w)
    print(f"\nModèle enregistré : {out / 'modele.json'}  (modifiable : sections, poutres, niveaux…)")
    print(f"Plan de contrôle : {out / 'controle_modele.dxf'}  (rouge = modèle reconnu, gris = plan importé)")
    print(f"Ensuite : koordinia calculer --modele {out / 'modele.json'} --norme bael -o {out}")
    return 0


def cmd_calculer(args) -> int:
    from .codes import get_code
    from .design import run
    from .outputs.drawings import group_types, plan_coffrage, plan_controle, plan_fondations, plan_ferraillage
    from .outputs.report import quantities, write_report

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    drawing = None
    if args.modele:
        bld = Building.load(args.modele)
        if args.niveaux_set:
            bld.n_levels = args.niveaux
        if args.hauteur_set:
            bld.floor_height = args.hauteur
    elif args.plan:
        bld, drawing = _import_model(args)
        bld.save(out / "modele.json")
    else:
        print("Indiquez un plan (.dwg/.dxf/.pdf) ou --modele modele.json", file=sys.stderr)
        return 2
    if not bld.columns:
        for w in bld.warnings:
            print("•", w)
        print("Aucun poteau exploitable : calcul impossible.", file=sys.stderr)
        return 1

    ls = LoadSettings(
        floor_type=args.plancher,
        g_floor=args.g_plancher, g_finishes=args.g_revetement, q_floor=args.q,
        g_roof_extra=args.g_terrasse, q_roof=args.q_terrasse, facade_load=args.facade,
        degression=not args.sans_degression,
    )
    code = get_code(args.norme, fc=args.fc, fy=args.fe, cover=args.enrobage)
    res = run(bld, ls, code, sigma_sol=args.sol)

    col_t, beam_t, foot_t = group_types(res)
    foot_names = {m: t.name for t in foot_t for m in t.members}
    files = []
    if bld.n_levels > 1:
        files.append(plan_coffrage(res, out / "plan_coffrage_etage_courant.dxf", "courant", 2))
    files.append(plan_coffrage(res, out / "plan_coffrage_terrasse.dxf", "terrasse", bld.n_levels))
    files.append(plan_fondations(res, out / "plan_fondations.dxf", foot_names))
    files.append(plan_ferraillage(res, out / "plans_ferraillage.dxf", col_t, beam_t, foot_t))
    if drawing is not None:
        files.append(plan_controle(bld, drawing, out / "controle_modele.dxf"))
    files += list(write_report(res, out))

    summary = {
        "norme": code.name,
        "niveaux": bld.n_levels,
        "metre": quantities(res),
        "poteaux": [{"id": r.column_id, "niveau": r.storey, "Nser_kN": round(r.nser, 1), "Nu_kN": round(r.nu, 1),
                     "section_cm": f"{r.design.b * 100:.0f}x{r.design.h * 100:.0f}", "armatures": str(r.design.bars),
                     "cadres": str(r.design.stirrups), "ok": r.design.ok} for r in res.columns],
        "poutres": [{"id": r.beam_id, "niveau": r.level, "portee_m": round(r.span, 2),
                     "section_cm": f"{r.design.b * 100:.0f}x{r.design.h * 100:.0f}",
                     "inf": str(r.design.bars_bottom), "sup": str(r.design.bars_top),
                     "cadres": str(r.design.stirrups), "ok": r.design.ok} for r in res.beams],
        "semelles": [{"poteau": f.column_id, "A_m": f.design.A, "B_m": f.design.B, "h_m": f.design.h,
                      "nappe_A": str(f.design.bars_x), "nappe_B": str(f.design.bars_y), "ok": f.design.ok}
                     for f in res.footings],
        "avertissements": list(dict.fromkeys(res.warnings)),
        "hypotheses_charges": asdict(ls),
    }
    (out / "resultats.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    files.append(out / "resultats.json")

    for w in dict.fromkeys(res.warnings):
        print("•", w)
    n_ko = sum(not r.design.ok for r in res.columns) + sum(not r.design.ok for r in res.beams) \
        + sum(not f.design.ok for f in res.footings)
    print(f"\nCalcul {code.name} : {len(res.columns)} tronçons de poteaux, {len(res.beams)} poutres, "
          f"{len(res.footings)} semelles — {n_ko} élément(s) non vérifié(s).")
    print("Fichiers produits :")
    for f in files:
        print("  -", f)
    return 0


def cmd_planches(args) -> int:
    from .importers import import_plan
    from .sheets import find_sheets

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page)
    sheets = find_sheets(drawing)
    if not sheets:
        print("Aucune planche (cadre) détectée : le dessin sera traité en entier.")
        return 0
    for sh in sheets:
        x0, y0, x1, y1 = sh.bbox
        tag = "plan" if sh.is_plan else "    "
        print(f"{sh.index:3d}. [{tag}] {sh.title}   ({x1 - x0:.0f} × {y1 - y0:.0f} m)")
    return 0


def cmd_exemple(args) -> int:
    from .sample import write_sample_dxf, write_sample_pdf

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    print(write_sample_dxf(out / "exemple_plan.dxf"))
    print(write_sample_pdf(out / "exemple_plan.pdf"))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="koordinia", description="Dimensionnement BA à partir de plans DWG/DXF/PDF")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detecter", help="Lire un plan et proposer le modèle structurel (à vérifier)")
    _add_import_args(d)
    d.set_defaults(func=cmd_detecter)

    c = sub.add_parser("calculer", help="Descente de charges + dimensionnement + plans + note de calcul")
    _add_import_args(c)
    c.add_argument("--modele", help="Modèle JSON (issu de « detecter », éventuellement corrigé)")
    c.add_argument("--norme", default="bael", choices=["bael", "ec2", "cm66", "ec3"], help="Règlement")
    c.add_argument("--fc", type=float, help="Résistance du béton fc28 / fck (MPa) — défaut 25")
    c.add_argument("--fe", type=float, help="Limite élastique de l'acier fe / fyk (MPa) — BAEL 400, EC2 500")
    c.add_argument("--enrobage", type=float, default=0.03, help="Enrobage (m)")
    c.add_argument("--plancher", default="corps_creux", choices=["corps_creux", "dalle_pleine"])
    c.add_argument("--g-plancher", type=float, default=2.85, help="Poids propre plancher (kN/m²) — 16+4 : 2,85")
    c.add_argument("--g-revetement", type=float, default=2.00, help="Revêtements + cloisons (kN/m²)")
    c.add_argument("--q", type=float, default=1.50, help="Exploitation étage courant (kN/m²)")
    c.add_argument("--g-terrasse", type=float, default=1.50, help="Étanchéité + forme de pente (kN/m²)")
    c.add_argument("--q-terrasse", type=float, default=1.00, help="Exploitation terrasse (kN/m²)")
    c.add_argument("--facade", type=float, default=0.0, help="Maçonnerie sur poutres de rive (kN/m)")
    c.add_argument("--sans-degression", action="store_true", help="Ne pas appliquer la dégression de Q")
    c.add_argument("--sol", type=float, default=0.20, help="Contrainte admissible du sol (MPa)")
    c.set_defaults(func=cmd_calculer)

    pl = sub.add_parser("planches", help="Lister les planches (cadres) d'un dessin")
    _add_import_args(pl)
    pl.set_defaults(func=cmd_planches)

    e = sub.add_parser("exemple", help="Générer un plan d'exemple (DXF + PDF)")
    e.add_argument("-o", "--sortie", default="exemple")
    e.set_defaults(func=cmd_exemple)

    raw = sys.argv[1:] if argv is None else argv
    args = p.parse_args(raw)
    args.niveaux_set = any(a.startswith("--niveaux") for a in raw)
    args.hauteur_set = any(a.startswith("--hauteur") for a in raw)
    try:
        return args.func(args)
    except (NotImplementedError, ValueError, RuntimeError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
