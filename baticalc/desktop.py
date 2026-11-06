"""BatiCalc en logiciel de bureau (Windows, Linux, macOS).

Le lanceur démarre le serveur BatiCalc sur l'ordinateur et ouvre l'application dans sa propre
fenêtre (Edge ou Chrome en mode application, sinon le navigateur par défaut). Une petite fenêtre
de contrôle permet de rouvrir l'application, de la **partager avec l'équipe** sur le réseau du
bureau et de quitter.

- Données : %LOCALAPPDATA%\\BatiCalc\\donnees (Windows), ~/.baticalc/donnees ailleurs.
- Une seule instance : relancer BatiCalc rouvre simplement la fenêtre.
- `BatiCalc.exe --test <fichier>` : auto-contrôle (calcul d'un plan d'exemple, démarrage du
  serveur) utilisé par la construction automatique de l'installateur.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "BatiCalc"
SHARED_PORT = 8000


# ----------------------------------------------------------------------------- emplacements
def base_dir() -> Path:
    """Dossier de l'exécutable (logiciel installé) ou du paquet (développement)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    d = Path(root) / APP if root else Path.home() / ".baticalc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_environment() -> None:
    """LibreDWG fourni avec le logiciel (dossier libredwg à côté de l'exécutable)."""
    for name in ("dwg2dxf.exe", "dwg2dxf"):
        for sub in ("libredwg", "libredwg/bin", "_internal/libredwg"):
            p = base_dir() / sub / name
            if p.exists():
                os.environ.setdefault("BATICALC_DWG2DXF", str(p))
                return


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # aucun paquet envoyé : choix de l'interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def free_port(preferred: int | None = None, host: str = "127.0.0.1") -> int:
    for port in ([preferred] if preferred else []) + [0]:
        with socket.socket() as s:
            try:
                s.bind((host, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("aucun port libre")


def alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/compte/inscription", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


# ----------------------------------------------------------------------------- serveur
class Server:
    def __init__(self, data: Path):
        self.data = data
        self.thread: threading.Thread | None = None
        self.server = None
        self.host = "127.0.0.1"
        self.port = 0

    def start(self, shared: bool = False) -> int:
        import uvicorn

        from .web import create_app

        self.stop()
        self.host = "0.0.0.0" if shared else "127.0.0.1"
        self.port = free_port(SHARED_PORT if shared else None, self.host)
        config = uvicorn.Config(create_app(self.data), host=self.host, port=self.port, log_level="warning",
                                proxy_headers=True, forwarded_allow_ips="*")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if alive(self.port):
                break
            time.sleep(0.1)
        (user_dir() / "instance.json").write_text(json.dumps({"port": self.port, "pid": os.getpid()}))
        return self.port

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=5)
        self.server = None

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def team_url(self) -> str:
        return f"http://{lan_address()}:{self.port}/"


def open_window(url: str) -> None:
    """Fenêtre d'application (Edge / Chrome --app), sinon navigateur par défaut."""
    candidates = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                candidates += [Path(root) / "Microsoft/Edge/Application/msedge.exe",
                               Path(root) / "Google/Chrome/Application/chrome.exe"]
    else:
        candidates += [Path(p) for p in filter(None, (shutil.which("chromium"), shutil.which("google-chrome"),
                                                      shutil.which("microsoft-edge")))]
    for exe in candidates:
        if exe.exists():
            profile = user_dir() / "fenetre"
            subprocess.Popen([str(exe), f"--app={url}", f"--user-data-dir={profile}", "--window-size=1366,860"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
    webbrowser.open(url)


# ----------------------------------------------------------------------------- fenêtre de contrôle
def control_window(srv: Server) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP)
    root.resizable(False, False)
    ico = base_dir() / "baticalc.ico"
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except tk.TclError:
            pass
    frm = ttk.Frame(root, padding=16)
    frm.grid()
    ttk.Label(frm, text="BatiCalc est en marche", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, sticky="w")
    status = tk.StringVar()
    shared = tk.BooleanVar(value=False)

    def refresh() -> None:
        if shared.get():
            status.set("Partagé avec l'équipe. Sur les autres postes et les tablettes du même réseau,\n"
                       f"ouvrir : {srv.team_url}")
        else:
            status.set("Utilisation sur cet ordinateur uniquement.")

    def toggle() -> None:
        srv.start(shared=shared.get())
        refresh()

    ttk.Label(frm, textvariable=status, justify="left").grid(column=0, row=1, sticky="w", pady=(6, 10))
    ttk.Checkbutton(frm, text="Partager avec l'équipe (réseau du bureau)", variable=shared,
                    command=toggle).grid(column=0, row=2, sticky="w")
    btns = ttk.Frame(frm)
    btns.grid(column=0, row=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Ouvrir BatiCalc", command=lambda: open_window(srv.local_url)).grid(column=0, row=0, padx=4)
    ttk.Button(btns, text="Dossier des données",
               command=lambda: webbrowser.open(srv.data.as_uri())).grid(column=1, row=0, padx=4)

    def quit_() -> None:
        srv.stop()
        try:
            (user_dir() / "instance.json").unlink()
        except OSError:
            pass
        root.destroy()

    ttk.Button(btns, text="Quitter", command=quit_).grid(column=2, row=0, padx=4)
    root.protocol("WM_DELETE_WINDOW", root.iconify)   # fermer = réduire ; « Quitter » arrête le serveur
    refresh()
    root.mainloop()


# ----------------------------------------------------------------------------- auto-contrôle
def self_test(report: Path) -> int:
    """Calcul complet d'un plan d'exemple + démarrage du serveur ; écrit un rapport."""
    lines, ok = [], True
    try:
        from .cli import main as cli
        from .sample import write_sample_dxf

        with tempfile.TemporaryDirectory() as tmp:
            plan = write_sample_dxf(Path(tmp) / "exemple.dxf")
            rc = cli(["calculer", str(plan), "-o", str(Path(tmp) / "res"), "--niveaux", "3"])
            produced = sorted(p.name for p in (Path(tmp) / "res").iterdir())
            lines.append(f"calcul : code {rc}, {len(produced)} fichiers")
            for need in ("note_de_calcul.pdf", "modele.ifc", "modele_saf.xlsx", "devis.xlsx"):
                if need not in produced:
                    ok = False
                    lines.append(f"MANQUANT : {need}")
            ok &= rc == 0
            srv = Server(Path(tmp) / "donnees")
            port = srv.start()
            up = alive(port)
            lines.append(f"serveur : {'OK' if up else 'ÉCHEC'} (port {port})")
            ok &= up
            srv.stop()
        tool = os.environ.get("BATICALC_DWG2DXF") or shutil.which("dwg2dxf")
        lines.append(f"LibreDWG : {tool or 'absent'}")
        if tool:   # le convertisseur se lance (bibliothèques présentes)
            pr = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            lines.append(f"  {(pr.stdout or pr.stderr).strip()[:80]} (code {pr.returncode})")
            ok &= pr.returncode == 0
        elif getattr(sys, "frozen", False) and sys.platform == "win32":
            ok = False
    except Exception as exc:  # pragma: no cover - rapporté dans le fichier
        import traceback

        ok = False
        lines.append(traceback.format_exc())
        lines.append(repr(exc))
    lines.append("RESULTAT : OK" if ok else "RESULTAT : ECHEC")
    report.write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- point d'entrée
def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is None or sys.stderr is None:   # exécutable Windows sans console
        log = open(user_dir() / "baticalc.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    setup_environment()
    if argv[:1] == ["--test"]:
        return self_test(Path(argv[1] if len(argv) > 1 else "baticalc_test.txt"))
    if argv and argv[0] not in ("--fenetre",):
        from .cli import main as cli   # BatiCalc.exe <commande> … : ligne de commande
        return cli(argv)
    inst = user_dir() / "instance.json"
    if inst.exists():
        try:
            port = json.loads(inst.read_text())["port"]
            if alive(port):
                open_window(f"http://127.0.0.1:{port}/")
                return 0
        except (ValueError, KeyError, OSError):
            pass
    from . import data_dir

    srv = Server(Path(data_dir(str(user_dir() / "donnees"))))
    srv.start()
    open_window(srv.local_url)
    try:
        control_window(srv)
    except ImportError:   # pas d'interface graphique (tkinter absent) : on garde le serveur actif
        print(f"{APP} : {srv.local_url}  (Ctrl+C pour arrêter)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    srv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
