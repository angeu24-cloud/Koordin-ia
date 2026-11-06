"""Logiciel de bureau : auto-contrôle (calcul d'exemple + serveur), instance unique."""
import json

from baticalc import desktop


def test_self_test(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    report = tmp_path / "rapport.txt"
    assert desktop.self_test(report) == 0, report.read_text(encoding="utf-8")
    assert "RESULTAT : OK" in report.read_text(encoding="utf-8")


def test_server_and_instance_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    srv = desktop.Server(tmp_path / "donnees")
    port = srv.start()
    try:
        assert desktop.alive(port)
        inst = json.loads((desktop.user_dir() / "instance.json").read_text())
        assert inst["port"] == port
        assert srv.local_url.endswith(f":{port}/")
    finally:
        srv.stop()
    assert not desktop.alive(port)
