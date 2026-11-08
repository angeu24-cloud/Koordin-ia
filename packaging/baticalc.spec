# -*- mode: python ; coding: utf-8 -*-
# Empaquetage PyInstaller de BatiCalc : pyinstaller packaging/baticalc.spec
# Produit dist/BatiCalc/ avec BatiCalc(.exe) (fenêtre) et baticalc(.exe) (ligne de commande).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent
WIN = sys.platform == "win32"

datas = collect_data_files("baticalc", includes=["data/*.json", "web/static/**/*"])
binaries = []
hidden = collect_submodules("baticalc") + collect_submodules("uvicorn")
for pkg in ("ifcopenshell", "pymupdf", "ezdxf", "openpyxl", "xlrd", "multipart", "python_multipart",
            "rapidocr_onnxruntime", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hidden += h
# LibreDWG (lecture des DWG), fourni par la construction automatique dans packaging/libredwg
ldwg = HERE / "libredwg"
if ldwg.exists():
    datas.append((str(ldwg), "libredwg"))
icon = str(HERE / "baticalc.ico")

a = Analysis(
    [str(HERE / "baticalc_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "pytest", "IPython", "PyQt5", "PyQt6", "PySide6", "ezdxf.addons.drawing.qtviewer",
              "pandas", "scipy", "torch", "pymupdf4llm", "pymupdf.layout"],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BatiCalc", console=not WIN, icon=icon,
          version=str(HERE / "version_info.txt") if WIN else None)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="baticalc-cli" if not WIN else "baticalc", console=True,
          icon=icon)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="BatiCalc")
