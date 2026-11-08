"""Interface en ligne de commande.

Exemples :
    baticalc exemple -o essai/
    baticalc detecter plan.dwg --niveaux 4 -o projet/
    baticalc calculer plan.pdf --echelle 100 --norme bael --niveaux 4 -o projet/
    baticalc calculer --modele projet/modele.json --norme ec2 -o projet/
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .model import Building, LoadSettings


def _add_import_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("plan", nargs="*", help="Plan(s) de l'architecte : .dwg, .dxf, .pdf, image scannée ; plusieurs fichiers "
                                          "(un par niveau, coupes, façades) sont assemblés comme des planches")
    p.add_argument("--echelle", type=int, help="PDF : échelle du plan (100 pour 1/100). Détectée si absente.")
    p.add_argument("--page", type=int, default=1, help="PDF : numéro de page (défaut 1)")
    p.add_argument("--unites", choices=["mm", "cm", "m"], help="DWG/DXF : unités du dessin si non définies")
    p.add_argument("--niveaux", type=int, default=1, help="Nombre de planchers au-dessus des fondations")
    p.add_argument("--hauteur", type=float, default=3.0, help="Hauteur d'étage (m)")
    p.add_argument("--portee-max", type=float, default=8.0, help="Portée maximale d'une poutre (m)")
    p.add_argument("--planche", help="Planche à traiter si le dessin en contient plusieurs : numéro ou mots du "
                                     "titre (ex. « etage courant »). Voir « baticalc planches ».")
    p.add_argument("--calque-poteaux", help="Calque des poteaux (nom exact ou expression régulière)")
    p.add_argument("--echelle-px-m", type=float, help="Plan scanné : échelle en pixels par mètre (sinon lue sur les cotes)")
    p.add_argument("--sans-contour", action="store_true",
                   help="Ne pas déduire le contour du plancher des murs (mailles de la trame uniquement)")
    p.add_argument("--tous-niveaux", action="store_true",
                   help="Modéliser chaque niveau avec sa propre planche (niveaux lus sur les coupes/façades)")
    p.add_argument("--affectation", help="Planche par niveau, ex. « RDC=3,ETAGE 2=4 » (numéros de « planches »)")
    p.add_argument("--hauteurs", help="Hauteurs imposées, ex. « RDC=3.29,RDJ=3.40 » (m)")
    p.add_argument("--liste-niveaux", help="Liste des niveaux si les coupes n'en donnent pas, "
                                          "ex. « RDC,ETAGE 1,ETAGE 2,TERRASSE »")
    p.add_argument("--sans-locaux", action="store_true",
                   help="Ne pas lire les locaux (usages, trémies, balcons) : charges uniformes")
    p.set_defaults(usages=None)
    p.add_argument("--config", help="Fichier de configuration du projet (baticalc.json, voir « baticalc init »)")
    p.add_argument("-o", "--sortie", default="resultats", help="Dossier de sortie")


# ----------------------------------------------------------------------------- configuration projet
CONFIG_TEMPLATE = {
    "_aide": ("Configuration BatiCalc d'un projet. Les chemins sont relatifs à ce fichier. "
              "Une option donnée en ligne de commande remplace la valeur d'ici. null = automatique."),
    "projet": {
        "nom": "Nom du projet",
        "plan": "plans/plan_architecte.dwg",
        "sortie": "resultats",
        "tous_niveaux": True,
    },
    "lecture": {
        "_aide": "planche : numéro ou mots du titre (plan unique) ; affectation : « RDC=3,ETAGE 2=4 » ; "
                 "hauteurs : « RDC=3.29 » ; liste_niveaux : « RDC,ETAGE 1,TERRASSE » si pas de coupe",
        "planche": None,
        "affectation": None,
        "hauteurs": None,
        "liste_niveaux": None,
        "calque_poteaux": None,
        "echelle": None,
        "echelle_px_m": None,
        "unites": None,
        "portee_max": 8.0,
        "niveaux": 1,
        "hauteur": 3.0,
    },
    "reglement": {"norme": "bael", "fc": 25.0, "fe": 400.0, "enrobage": 0.03},
    "charges": {
        "_aide": ("kN/m² ; plancher : corps_creux ou dalle_pleine ; facade en kN/m sur poutres de rive ; longrines : "
                  "maçonnerie du niveau bas portée par des longrines (kN/m), 0 sans longrines. Toiture légère "
                  "(charpente + tôles) : plancher dalle_pleine, g_plancher = poids de la couverture, g_terrasse = 0"),
        "plancher": "corps_creux",
        "g_plancher": 2.85,
        "g_revetement": 2.0,
        "q": 1.5,
        "g_terrasse": 1.5,
        "q_terrasse": 1.0,
        "facade": 0.0,
        "longrines": 0.0,
        "degression": True,
    },
    "sol": {"_aide": ("geotech : geotech.json produit par « baticalc geotech rapport.pdf » (à valider) ; "
                      "sol : contrainte admissible ELS imposée (MPa), prioritaire sur le rapport ; 0,20 si rien"),
            "geotech": None, "sol": None},
    "devis": {
        "_aide": ("bpu : bordereau de prix importé (baticalc bpu BORDEREAU.xls) ; categorie : 1ERE à 4EME "
                  "(terrain des fouilles) ; dosage : béton de fondation (kg/m³) ; hourdis : « 16 + 4 », « 20 + 5 »… "
                  "(vide = déduit du poids du plancher) ; tva : 0.18"),
        "bpu": None, "categorie": "2EME", "dosage": 350, "hourdis": None, "tva": 0.18,
    },
    "usages": {
        "_aide": ("Règles d'usage propres au projet, prioritaires sur le catalogue baticalc/data/usages.json. "
                  "Exemple : {\"nom\": \"Salle serveurs\", \"motifs\": [\"SERVEUR\"], \"q\": 7.5, \"type\": \"local\"}"),
        "regles": [],
    },
}

_PATH_KEYS = ("plan", "modele", "sortie", "geotech")


def _flatten(cfg: dict) -> dict:
    out = {}
    for k, v in cfg.items():
        if k.startswith("_"):
            continue
        if k == "usages" and isinstance(v, dict):
            out["usages"] = v.get("regles") or None
            continue
        if k == "devis" and isinstance(v, dict):
            out["devis"] = {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
            continue
        if isinstance(v, dict):
            out.update(_flatten(v))
        else:
            out[k.replace("-", "_")] = v
    return out


def apply_config(args, parser: argparse.ArgumentParser, raw: list[str]) -> None:
    """Complète `args` avec le fichier de configuration (les options explicites priment)."""
    path = Path(args.config)
    if not path.exists():
        raise ValueError(f"Fichier de configuration introuvable : {path}")
    cfg = _flatten(json.loads(path.read_text(encoding="utf-8")))
    if "degression" in cfg:
        cfg["sans_degression"] = not cfg.pop("degression")
    given: set[str] = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if any(a == opt or a.startswith(opt + "=") for a in raw):
                given.add(action.dest)
    positional_plan = getattr(args, "plan", None) is not None
    for key, val in cfg.items():
        if key == "nom":
            args.nom = val
            continue
        if not hasattr(args, key) or key in given or val is None:
            continue
        if key == "plan" and positional_plan:
            continue
        if key in _PATH_KEYS:
            val = [str((path.parent / v).resolve()) for v in val] if isinstance(val, list) else \
                str((path.parent / val).resolve())
        setattr(args, key, val)
        if key == "niveaux":
            args.niveaux_set = True
        if key == "hauteur":
            args.hauteur_set = True
    if isinstance(getattr(args, "devis", None), dict) and args.devis.get("bpu"):
        args.devis["bpu"] = str((path.parent / args.devis["bpu"]).resolve())
    if "sortie" not in given and "sortie" not in cfg:
        args.sortie = str(path.parent / "resultats")


def cmd_geotech(args) -> int:
    from .geotech import GeotechData, Value, extract, summary_lines

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "geotech.json"
    if args.vierge:
        g = GeotechData(fichier="saisie manuelle")
        g.contrainte_admissible_els = Value(0.20, "MPa", "à saisir d'après le rapport")
        g.profondeur_ancrage = Value(1.5, "m", "à saisir d'après le rapport")
        g.type_fondation = Value("superficielles", "", "superficielles | filantes | radier | pieux")
        g.save(path)
        print(f"{path} créé : remplacez les valeurs par celles du rapport, puis passez « valide » à true.")
        return 0
    if not args.rapport:
        raise ValueError("Indiquez le rapport géotechnique (PDF, TXT, DOCX) ou --vierge.")
    g = extract(args.rapport)
    g.save(path)
    print(f"Rapport : {args.rapport}\n")
    for k, v, src in summary_lines(g):
        print(f"  {k:30s} {v:16s} {src[:110]}")
    for r in g.remarques:
        print("•", r)
    print(f"\nValeurs enregistrées dans {path} avec « valide » : false.")
    print("Contrôlez-les (et corrigez-les si besoin) puis passez « valide » à true ;")
    print(f"ensuite : baticalc calculer … --geotech {path}   (ou « sol » → « geotech » dans baticalc.json)")
    return 0


def cmd_init(args) -> int:
    folder = Path(args.dossier)
    folder.mkdir(parents=True, exist_ok=True)
    cfg_path = folder / "baticalc.json"
    if cfg_path.exists() and not args.force:
        print(f"{cfg_path} existe déjà (utilisez --force pour le remplacer).", file=sys.stderr)
        return 1
    cfg = json.loads(json.dumps(CONFIG_TEMPLATE))
    if args.nom:
        cfg["projet"]["nom"] = args.nom
    if args.plan:
        import shutil

        (folder / "plans").mkdir(exist_ok=True)
        rel = []
        for p_ in (args.plan if isinstance(args.plan, list) else [args.plan]):
            src = Path(p_)
            dst = folder / "plans" / src.name
            if src.resolve() != dst.resolve():
                shutil.copyfile(src, dst)
            rel.append(f"plans/{src.name}")
        cfg["projet"]["plan"] = rel[0] if len(rel) == 1 else rel
    if args.norme:
        cfg["reglement"]["norme"] = args.norme
        cfg["reglement"]["fe"] = 500.0 if args.norme == "ec2" else 400.0
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Projet créé : {folder}")
    print(f"  - configuration : {cfg_path}  (charges, sol, norme, planches… à compléter)")
    if args.plan:
        print(f"  - plan(s) copié(s) dans {folder / 'plans'}")
    print(f"Ensuite : baticalc niveaux --config {cfg_path}")
    print(f"          baticalc calculer --config {cfg_path}")
    return 0


def _parse_map(txt: str | None, cast) -> dict:
    from .levels import canonical_level

    out = {}
    for part in (txt or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[canonical_level(k.strip()) or k.strip().upper()] = cast(v.strip())
    return out


def _import_project(args):
    from .importers import import_plan
    from .project import build_project

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page,
                          px_per_m=getattr(args, "echelle_px_m", None))
    proj = build_project(
        drawing, overrides=_parse_map(args.affectation, int), heights=_parse_map(args.hauteurs, float),
        levels_spec=[n.strip() for n in args.liste_niveaux.split(",")] if args.liste_niveaux else None,
        column_layer=args.calque_poteaux, max_span=args.portee_max, footprint=not args.sans_contour,
        default_height=args.hauteur, rooms=not args.sans_locaux, usages=args.usages,
    )
    return proj, drawing


def _control_plans(proj, drawing, out: Path) -> list[Path]:
    """Un plan de contrôle par planche utilisée."""
    from .outputs.drawings import plan_controle
    from .sheets import crop, find_sheets

    sheets = {s.title: s for s in find_sheets(drawing)}
    files, done = [], set()
    for k, st in enumerate(proj.storeys):
        title = st.sheet.split(" (")[0]
        if title in done or title not in sheets:
            continue
        done.add(title)
        path = out / f"controle_{k + 1:02d}_{_slug(st.name)}.dxf"
        files.append(plan_controle(st.plan, crop(drawing, sheets[title].bbox), path))
    return files


def _hourdis_for(g_floor: float) -> str:
    for lim, name in ((2.95, "16 + 4"), (3.45, "20 + 5"), (4.05, "25 + 5")):
        if g_floor <= lim:
            return name
    return "30 + 5"


def _write_mep(proj, out: Path, files: list, mep=None) -> object:
    """Réseaux (plomberie, électricité, climatisation) : calcul, plans DXF, reseaux.json."""
    from dataclasses import asdict as _asdict

    from .mep.design import design_mep
    from .mep.drawings import write_mep_drawings

    mep = mep or design_mep(proj)
    data = {"storeys": [{k: v for k, v in _asdict(s).items() if k not in ("lights", "sockets", "switches")}
                        for s in mep.storeys], "colonnes": mep.columns, "tgbt": mep.tgbt, "notes": mep.notes,
            "quantites": {k: round(v[0], 2) for k, v in mep.quantities.items()}}
    (out / "reseaux.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=_json_default),
                                      encoding="utf-8")
    files += write_mep_drawings(proj, mep, out) + [out / "reseaux.json"]
    for n in mep.notes:
        print("•", n)
    return mep


def _base_loads(res) -> dict:
    from .interop.robot_export import base_loads

    return base_loads(res)


def _write_analysis_links(res, out: Path) -> list[Path]:
    """Liens directs vers les logiciels de calcul : SAF (Graitec Advance Design, SCIA, RFEM…) et Robot."""
    from .interop.analytical import build_analytical
    from .interop.robot_export import export_robot
    from .interop.saf_export import export_saf

    model = build_analytical(res)
    files = [export_saf(res, out / "modele_saf.xlsx", model)]
    files += export_robot(res, out, model)
    for n in model.notes[:-1]:
        print("•", n)
    return files


def cmd_robot_comparer(args) -> int:
    from .interop.robot_export import compare_reactions

    out = Path(args.resultats)
    summary = json.loads((out / "resultats.json").read_text(encoding="utf-8"))
    csv_path = Path(args.csv) if args.csv else out / "robot" / "robot_reactions.csv"
    rows = compare_reactions(summary.get("charges_pied_poteaux_kN", {}), csv_path)
    print(f"{'Poteau':<8}{'Robot G':>10}{'Robot Q':>10}{'BatiCalc G':>11}{'BatiCalc Q':>11}{'Écart':>9}")
    for r in rows:
        kg = f"{r['baticalc_G']:>11.1f}" if r["baticalc_G"] is not None else f"{'—':>11}"
        kq = f"{r['baticalc_Q']:>11.1f}" if r["baticalc_Q"] is not None else f"{'—':>11}"
        ec = f"{r['ecart_pct']:>8.1f}%" if r["ecart_pct"] is not None else f"{'—':>9}"
        print(f"{r['poteau']:<8}{r['robot_G']:>10.1f}{r['robot_Q']:>10.1f}{kg}{kq}{ec}")
    (out / "robot" / "comparaison_robot.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    big = [r for r in rows if r["ecart_pct"] is not None and abs(r["ecart_pct"]) > 15]
    if big:
        print(f"\n{len(big)} poteau(x) avec un écart > 15 % : effet de continuité / portique à examiner "
              f"({', '.join(r['poteau'] for r in big)}).")
    return 0


def _write_devis(res, args, out: Path, ls, mep=None) -> list[Path]:
    """Devis quantitatif et estimatif (Excel + JSON) ; prix du bordereau s'il est fourni."""
    try:
        from .costing.bpu import Bordereau, import_bpu
        from .costing.devis import build_devis, write_excel
        from .costing.metre import DevisSettings
    except ImportError:  # pragma: no cover
        return []
    cfg = dict(getattr(args, "devis", None) or {})
    if getattr(args, "bpu", None):
        cfg["bpu"] = args.bpu
    bpu = None
    src = cfg.pop("bpu", None)
    if src:
        sp = Path(src)
        bpu = Bordereau.load(sp) if sp.suffix.lower() == ".json" else import_bpu(sp)
    if not cfg.get("hourdis"):
        cfg["hourdis"] = _hourdis_for(ls.g_floor)
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("• Devis Excel indisponible : installez openpyxl.")
        return []
    dv = build_devis(res, bpu, DevisSettings.from_dict(cfg), mep=mep)
    (out / "devis.json").write_text(json.dumps(dv.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    files = [write_excel(dv, out / "devis.xlsx"), out / "devis.json"]
    print(f"Devis : {dv.total_ht:,.0f} {dv.currency} HT".replace(",", " ") +
          (f" (bordereau {dv.bpu_source})" if bpu else " (quantités seules, pas de bordereau)"))
    return files


def cmd_bpu(args) -> int:
    from .costing.bpu import import_bpu

    b = import_bpu(args.bordereau)
    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "bpu.json"
    b.save(path)
    for n in b.notes:
        print("•", n)
    print(f"Bordereau enregistré : {path}")
    print("Dans baticalc.json : \"devis\": {\"bpu\": \"bpu.json\"}  (ou calculer … --bpu bpu.json)")
    return 0


def _json_default(o):
    """Types numpy → types Python pour l'export JSON."""
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"{type(o).__name__} non sérialisable")


def _slug(name: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _import_model(args) -> tuple[Building, object | None]:
    from .importers import import_plan
    from .recognition import build_model

    from .sheets import crop, find_sheets, select_sheet

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page,
                          px_per_m=getattr(args, "echelle_px_m", None))
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
                      column_layer=args.calque_poteaux, footprint=not args.sans_contour,
                      rooms=not args.sans_locaux, usages=args.usages)
    return bld, drawing


def cmd_detecter(args) -> int:
    from .outputs.drawings import plan_controle

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    if args.tous_niveaux:
        proj, drawing = _import_project(args)
        proj.save(out / "projet.json")
        files = _control_plans(proj, drawing, out)
        for w in dict.fromkeys(proj.warnings):
            print("•", w)
        print()
        for st in proj.storeys:
            print(f"  {st.name:10s} h = {st.height:.2f} m  {len(st.plan.columns):3d} poteaux  "
                  f"{len(st.plan.beams):3d} poutres  ← {st.sheet}")
        print(f"\nProjet enregistré : {out / 'projet.json'}")
        for f in files:
            print("Plan de contrôle :", f)
        print(f"Ensuite : baticalc calculer --modele {out / 'projet.json'} --norme bael -o {out}")
        return 0
    bld, drawing = _import_model(args)
    bld.save(out / "modele.json")
    plan_controle(bld, drawing, out / "controle_modele.dxf")
    for w in bld.warnings:
        print("•", w)
    print(f"\nModèle enregistré : {out / 'modele.json'}  (modifiable : sections, poutres, niveaux…)")
    print(f"Plan de contrôle : {out / 'controle_modele.dxf'}  (rouge = modèle reconnu, gris = plan importé)")
    print(f"Ensuite : baticalc calculer --modele {out / 'modele.json'} --norme bael -o {out}")
    return 0


def cmd_calculer(args) -> int:
    from .codes import get_code
    from .design import run
    from .outputs.drawings import group_types, plan_coffrage, plan_controle, plan_fondations, plan_ferraillage
    from .outputs.report import quantities, write_report

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    from .project import Project

    drawing = None
    if args.modele:
        proj = Project.load(args.modele)
        if proj.single_plan:
            bld = proj.storeys[0].plan
            if args.niveaux_set:
                bld.n_levels = args.niveaux
            if args.hauteur_set:
                bld.floor_height = args.hauteur
            proj = Project.from_building(bld)
    elif args.plan and isinstance(args.plan, str) and Path(args.plan).suffix.lower() == ".ifc":
        from .interop.ifc_import import import_ifc

        proj = import_ifc(args.plan, max_span=args.portee_max)
        proj.save(out / "projet.json")
    elif args.plan and args.tous_niveaux:
        proj, drawing = _import_project(args)
        proj.save(out / "projet.json")
    elif args.plan:
        bld, drawing = _import_model(args)
        bld.save(out / "modele.json")
        proj = Project.from_building(bld)
    else:
        print("Indiquez un plan (.dwg/.dxf/.pdf) ou --modele modele.json / projet.json", file=sys.stderr)
        return 2
    if not proj.storeys or not proj.storeys[-1].plan.columns:
        for w in proj.warnings:
            print("•", w)
        print("Aucun poteau exploitable : calcul impossible.", file=sys.stderr)
        return 1

    ls = LoadSettings(
        floor_type=args.plancher,
        g_floor=args.g_plancher, g_finishes=args.g_revetement, q_floor=args.q,
        g_roof_extra=args.g_terrasse, q_roof=args.q_terrasse, facade_load=args.facade,
        degression=not args.sans_degression, ground_wall_load=getattr(args, "longrines", 0.0) or 0.0,
    )
    code = get_code(args.norme, fc=args.fc, fy=args.fe, cover=args.enrobage)
    if args.nom:
        proj.name = args.nom
    geo = None
    if args.geotech:
        from .geotech import GeotechData, extract

        gp = Path(args.geotech)
        geo = GeotechData.load(gp) if gp.suffix.lower() == ".json" else extract(gp)
        if gp.suffix.lower() != ".json":
            geo.save(out / "geotech.json")
    res = run(proj, ls, code, sigma_sol=args.sol, geotech=geo)

    col_t, beam_t, foot_t = group_types(res)
    foot_names = {m: t.name for t in foot_t for m in t.members}
    files = []
    if proj.single_plan:
        bld = proj.storeys[0].plan
        if proj.n > 1:
            files.append(plan_coffrage(res, out / "plan_coffrage_etage_courant.dxf", "courant", 2))
        if ls.floor_type == "charpente":
            files.append(plan_coffrage(res, out / "plan_chainage_haut.dxf", "terrasse", proj.n,
                                       title="PLAN DES POTEAUX ET DU CHAÎNAGE HAUT (sous charpente)"))
        else:
            files.append(plan_coffrage(res, out / "plan_coffrage_terrasse.dxf", "terrasse", proj.n))
        if drawing is not None:
            files.append(plan_controle(bld, drawing, out / "controle_modele.dxf"))
    else:
        for k, st in enumerate(proj.storeys):
            label = proj.floor_label(k)
            files.append(plan_coffrage(res, out / f"coffrage_{k + 1:02d}_{_slug(label)}.dxf", label, k + 1,
                                       plan=st.plan, title=f"PLAN DE COFFRAGE — {label.upper()}"))
        if drawing is not None:
            files += _control_plans(proj, drawing, out)
    files.append(plan_fondations(res, out / "plan_fondations.dxf", foot_names))
    files.append(plan_ferraillage(res, out / "plans_ferraillage.dxf", col_t, beam_t, foot_t))
    mep = None
    if not getattr(args, "sans_reseaux", False):
        from .mep.design import design_mep

        mep = design_mep(proj)
    files += list(write_report(res, out, mep))
    from .outputs.viewer import write_viewer

    files.append(write_viewer(res, out))
    try:
        from .interop.ifc_export import export_ifc

        files.append(export_ifc(res, out / "modele.ifc"))
    except ImportError:
        print("• Export IFC indisponible : installez ifcopenshell (pip install ifcopenshell).")
    files += _write_analysis_links(res, out)
    if mep is not None:
        _write_mep(proj, out, files, mep)
    files += _write_devis(res, args, out, ls, mep)

    config_used = {k: v for k, v in vars(args).items()
                   if k not in ("func", "niveaux_set", "hauteur_set", "cmd") and not callable(v)}
    summary = {
        "projet": proj.name or None,
        "norme": code.name,
        "niveaux": [{"nom": st.name, "hauteur_m": st.height, "planche": st.sheet} for st in proj.storeys],
        "metre": quantities(res),
        "poteaux": [{"id": r.column_id, "niveau": r.storey_name or r.storey, "Nser_kN": round(r.nser, 1), "Nu_kN": round(r.nu, 1),
                     "section_cm": f"{r.design.b * 100:.0f}x{r.design.h * 100:.0f}", "armatures": str(r.design.bars),
                     "cadres": str(r.design.stirrups), "ok": r.design.ok} for r in res.columns],
        "poutres": [{"id": r.beam_id, "niveau": r.level, "portee_m": round(r.span, 2),
                     "section_cm": f"{r.design.b * 100:.0f}x{r.design.h * 100:.0f}",
                     "inf": str(r.design.bars_bottom), "sup": str(r.design.bars_top),
                     "cadres": str(r.design.stirrups), "ok": r.design.ok} for r in res.beams],
        "longrines": [{"id": r.beam_id, "portee_m": round(r.span, 2), "section_cm": f"{r.design.b * 100:.0f}x{r.design.h * 100:.0f}",
                       "inf": str(r.design.bars_bottom), "sup": str(r.design.bars_top), "cadres": str(r.design.stirrups),
                       "ok": r.design.ok} for r in res.longrines],
        "fondations": res.foundation_type,
        "radier": res.raft,
        "pieux": res.piles,
        "semelles": [{"poteau": f.column_id, "sous_mur": f.on_wall, "A_m": f.design.A, "B_m": f.design.B, "h_m": f.design.h,
                      "nappe_A": str(f.design.bars_x), "nappe_B": str(f.design.bars_y), "ok": f.design.ok}
                     for f in res.footings],
        "avertissements": list(dict.fromkeys(res.warnings)),
        "charges_pied_poteaux_kN": _base_loads(res),
        "hypotheses_charges": asdict(ls),
        "configuration": config_used,
    }
    (out / "resultats.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default),
                                        encoding="utf-8")
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

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page,
                          px_per_m=getattr(args, "echelle_px_m", None))
    sheets = find_sheets(drawing)
    if not sheets:
        print("Aucune planche (cadre) détectée : le dessin sera traité en entier.")
        return 0
    for sh in sheets:
        x0, y0, x1, y1 = sh.bbox
        tag = "plan" if sh.is_plan else "    "
        print(f"{sh.index:3d}. [{tag}] {sh.title}   ({x1 - x0:.0f} × {y1 - y0:.0f} m)")
    return 0


def cmd_niveaux(args) -> int:
    from .importers import import_plan
    from .levels import display_name
    from .project import candidate_resolver, plan_storeys, resolve_candidates

    drawing = import_plan(args.plan, units=args.unites, scale=args.echelle, page=args.page,
                          px_per_m=getattr(args, "echelle_px_m", None))
    storeys, sheets, notes = plan_storeys(
        drawing, overrides=_parse_map(args.affectation, int), heights=_parse_map(args.hauteurs, float),
        levels_spec=[n.strip() for n in args.liste_niveaux.split(",")] if args.liste_niveaux else None,
        default_height=args.hauteur)
    notes += resolve_candidates(storeys, sheets, *candidate_resolver(drawing, args.calque_poteaux))
    for n in notes:
        print("•", n)
    z = 0.0
    print()
    for sp in storeys:
        title = sp.sheet.title if sp.sheet else "— aucune —"
        no = sp.sheet.index if sp.sheet else "-"
        print(f"  {display_name(sp.name):10s} +{z:6.2f}  h = {sp.height:.2f} m   planche {no} « {title} » ({sp.reason})")
        z += sp.height
    print(f"  {'Terrasse':10s} +{z:6.2f}")
    print("\nPour corriger : --affectation « RDC=3 » (numéro de planche), --hauteurs « RDC=3.30 ».")
    return 0


def cmd_serveur(args) -> int:
    import uvicorn

    from .web import create_app

    from . import data_dir

    donnees = data_dir(args.donnees)
    app = create_app(donnees, inscription=args.inscription, code_inscription=args.code_inscription)
    print(f"BatiCalc : http://{args.hote}:{args.port}  (données : {Path(donnees).resolve()})")
    # en-têtes X-Forwarded-* acceptés : derrière un proxy HTTPS (Caddy, Nginx), cookies « secure »
    uvicorn.run(app, host=args.hote, port=args.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips="*")
    return 0


def cmd_exemple(args) -> int:
    from .sample import write_sample_dxf, write_sample_pdf

    out = Path(args.sortie)
    out.mkdir(parents=True, exist_ok=True)
    print(write_sample_dxf(out / "exemple_plan.dxf"))
    print(write_sample_pdf(out / "exemple_plan.pdf"))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="baticalc", description="Dimensionnement BA à partir de plans DWG/DXF/PDF")
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
    c.add_argument("--plancher", default="corps_creux", choices=["corps_creux", "dalle_pleine", "charpente"])
    c.add_argument("--g-plancher", type=float, default=2.85, help="Poids propre plancher (kN/m²) — 16+4 : 2,85")
    c.add_argument("--g-revetement", type=float, default=2.00, help="Revêtements + cloisons (kN/m²)")
    c.add_argument("--q", type=float, default=1.50, help="Exploitation étage courant (kN/m²)")
    c.add_argument("--g-terrasse", type=float, default=1.50, help="Étanchéité + forme de pente (kN/m²)")
    c.add_argument("--q-terrasse", type=float, default=1.00, help="Exploitation terrasse (kN/m²)")
    c.add_argument("--facade", type=float, default=0.0, help="Maçonnerie sur poutres de rive (kN/m)")
    c.add_argument("--longrines", type=float, default=0.0,
                   help="Maçonnerie du niveau bas portée par des longrines (kN/m) ; 0 : pas de longrines")
    c.add_argument("--sans-degression", action="store_true", help="Ne pas appliquer la dégression de Q")
    c.add_argument("--sol", type=float, default=None,
                   help="Contrainte admissible du sol (MPa) ; sinon celle du rapport géotechnique, sinon 0,20")
    c.add_argument("--sans-reseaux", action="store_true", help="Ne pas calculer les réseaux (plomberie, élec, clim)")
    c.add_argument("--bpu", help="Bordereau de prix pour le devis : bpu.json, .xls, .xlsx ou .csv")
    c.set_defaults(devis=None)
    c.add_argument("--geotech", help="Données géotechniques : geotech.json (validé) ou rapport PDF à lire")
    c.set_defaults(func=cmd_calculer)

    pl = sub.add_parser("planches", help="Lister les planches (cadres) d'un dessin")
    _add_import_args(pl)
    pl.set_defaults(func=cmd_planches)

    nv = sub.add_parser("niveaux", help="Lister les niveaux (coupes/façades) et les planches affectées")
    _add_import_args(nv)
    nv.set_defaults(func=cmd_niveaux)

    bp = sub.add_parser("bpu", help="Importer un bordereau de prix (xls, xlsx, csv) → bpu.json")
    bp.add_argument("bordereau")
    bp.add_argument("-o", "--sortie", default=".")
    bp.set_defaults(func=cmd_bpu)

    gt = sub.add_parser("geotech", help="Lire un rapport géotechnique (PDF/TXT/DOCX) → geotech.json à valider")
    gt.add_argument("rapport", nargs="?", help="Rapport géotechnique")
    gt.add_argument("--vierge", action="store_true", help="Créer un geotech.json à remplir à la main")
    gt.add_argument("-o", "--sortie", default=".", help="Dossier où écrire geotech.json")
    gt.set_defaults(func=cmd_geotech)

    it = sub.add_parser("init", help="Créer le dossier d'un nouveau projet avec son fichier de configuration")
    it.add_argument("dossier", help="Dossier du projet")
    it.add_argument("--plan", nargs="+", help="Plan(s) d'architecte à copier dans le projet")
    it.add_argument("--nom", help="Nom du projet")
    it.add_argument("--norme", choices=["bael", "ec2"])
    it.add_argument("--force", action="store_true", help="Remplacer une configuration existante")
    it.set_defaults(func=cmd_init)

    sv = sub.add_parser("serveur", help="Lancer l'application web (équipe, navigateur, tablette)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--hote", default="0.0.0.0", help="Adresse d'écoute (0.0.0.0 = accessible sur le réseau)")
    sv.add_argument("--donnees", default="donnees_baticalc", help="Dossier des comptes, projets et fichiers")
    sv.add_argument("--inscription", choices=["ouverte", "fermee"],
                    help="ouverte : tout visiteur peut créer un compte ; fermee : seul le premier compte")
    sv.add_argument("--code-inscription", help="Code d'invitation exigé pour créer un compte")
    sv.set_defaults(func=cmd_serveur)

    rc = sub.add_parser("robot-comparer", help="Comparer les réactions calculées par Robot à la descente de charges")
    rc.add_argument("resultats", help="Dossier des résultats BatiCalc (contient resultats.json et robot/)")
    rc.add_argument("--csv", help="Fichier robot_reactions.csv (par défaut : <resultats>/robot/robot_reactions.csv)")
    rc.set_defaults(func=cmd_robot_comparer)

    e = sub.add_parser("exemple", help="Générer un plan d'exemple (DXF + PDF)")
    e.add_argument("-o", "--sortie", default="exemple")
    e.set_defaults(func=cmd_exemple)

    raw = sys.argv[1:] if argv is None else argv
    args = p.parse_args(raw)
    if isinstance(getattr(args, "plan", None), list):   # un fichier : chemin simple ; plusieurs : liste
        args.plan = None if not args.plan else (args.plan[0] if len(args.plan) == 1 else args.plan)
    args.niveaux_set = any(a.startswith("--niveaux") for a in raw)
    args.hauteur_set = any(a.startswith("--hauteur") for a in raw)
    args.nom = getattr(args, "nom", None)
    try:
        if getattr(args, "config", None):
            sp = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
            apply_config(args, sp.choices[args.cmd], raw)
        if args.cmd in ("detecter", "calculer", "planches", "niveaux") and not args.plan \
                and not getattr(args, "modele", None):
            raise ValueError("Indiquez un plan (.dwg/.dxf/.pdf), --modele, ou --config baticalc.json")
        return args.func(args)
    except (NotImplementedError, ValueError, RuntimeError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
