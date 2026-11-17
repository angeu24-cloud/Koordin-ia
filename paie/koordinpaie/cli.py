"""Ligne de commande : lancement du serveur et calcul rapide d'un salaire."""
from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="koordinpaie", description="Gestion des contrats et de la paie")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sv = sub.add_parser("serveur", help="lancer l'application web")
    sv.add_argument("--hote", default="127.0.0.1", help="0.0.0.0 pour l'ouvrir au réseau du bureau")
    sv.add_argument("--port", type=int, default=8100)
    sv.add_argument("--donnees", default="donnees_koordinpaie", help="dossier de la base de données")

    cal = sub.add_parser("calcul", help="calculer un bulletin à partir d'un salaire de base")
    cal.add_argument("salaire_base", type=float)
    cal.add_argument("--embauche", default=None, help="date d'embauche AAAA-MM-JJ")
    cal.add_argument("--marie", action="store_true")
    cal.add_argument("--enfants", type=int, default=0)
    cal.add_argument("--transport", type=float, default=0)
    cal.add_argument("--periode", default=None, help="AAAA-MM (mois en cours par défaut)")

    a = ap.parse_args(argv)
    if a.cmd == "serveur":
        import uvicorn

        from .app import creer_app

        print(f"Koordin Paie : http://{'localhost' if a.hote in ('127.0.0.1', '0.0.0.0') else a.hote}:{a.port}")
        uvicorn.run(creer_app(a.donnees), host=a.hote, port=a.port)
        return 0

    from datetime import date

    from .calcul import calculer_dict

    an, mo = (int(x) for x in (a.periode or date.today().strftime("%Y-%m")).split("-"))
    r = calculer_dict({"date_embauche": a.embauche or f"{an}-{mo:02d}-01", "marie": a.marie, "enfants": a.enfants},
                      {"salaire_base": a.salaire_base, "transport": a.transport}, {}, an, mo)
    for k in ("brut", "brut_imposable", "cnps_salarie", "cmu_salarie", "its", "net_a_payer", "charges_patronales",
              "cout_employeur"):
        print(f"{k:20s} {r[k]:>12,}".replace(",", " "))
    if r["alertes"]:
        print(json.dumps(r["alertes"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
