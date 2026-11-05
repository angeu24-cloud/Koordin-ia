"""Fichier de configuration par projet : création, utilisation, priorité de la ligne de commande."""
import json

from koordinia.cli import main
from koordinia.sample import write_sample_dxf


def test_init_and_calculate_with_config(tmp_path):
    plan = write_sample_dxf(tmp_path / "archi.dxf")
    proj = tmp_path / "Immeuble_Test"
    assert main(["init", str(proj), "--plan", str(plan), "--nom", "Immeuble test R+3"]) == 0
    cfg_path = proj / "koordinia.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["projet"]["plan"] == "plans/archi.dxf"
    assert (proj / "plans" / "archi.dxf").exists()
    # hypothèses du projet
    cfg["projet"]["tous_niveaux"] = False
    cfg["lecture"]["niveaux"] = 4
    cfg["charges"]["q"] = 2.5
    cfg["sol"]["sol"] = 0.15
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    # refus de remplacer une configuration existante
    assert main(["init", str(proj)]) == 1

    assert main(["calculer", "--config", str(cfg_path)]) == 0
    res = json.loads((proj / "resultats" / "resultats.json").read_text(encoding="utf-8"))
    assert res["projet"] == "Immeuble test R+3"
    assert res["hypotheses_charges"]["q_floor"] == 2.5
    assert res["configuration"]["sol"] == 0.15
    assert len(res["niveaux"]) == 4

    # une option en ligne de commande remplace la configuration
    assert main(["calculer", "--config", str(cfg_path), "--q", "5.0", "--norme", "ec2", "-o",
                 str(proj / "variante")]) == 0
    var = json.loads((proj / "variante" / "resultats.json").read_text(encoding="utf-8"))
    assert var["hypotheses_charges"]["q_floor"] == 5.0
    assert var["norme"].startswith("Eurocode 2")
    assert var["configuration"]["sol"] == 0.15


def test_missing_plan_message(tmp_path, capsys):
    assert main(["calculer", "-o", str(tmp_path)]) == 1
    assert "koordinia.json" in capsys.readouterr().err
