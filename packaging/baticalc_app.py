"""Point d'entrée du logiciel de bureau BatiCalc (empaqueté par PyInstaller)."""
import sys

from baticalc.desktop import main

if __name__ == "__main__":
    sys.exit(main())
