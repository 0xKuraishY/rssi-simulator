"""Construction de l'exécutable autonome avec PyInstaller (Windows / Linux).

    python build.py               # séparateur --add-data déduit de la plateforme
    python build.py --sep ";"     # forcer le séparateur Windows
    python build.py --onedir      # dossier plutôt qu'un fichier unique

Le modèle d'IA n'est jamais embarqué (objectif : exécutable < 50 Mo).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIRS = ("scenarios", "data", "assets")
EXCLUDES = ("llama_cpp", "tkinter", "unittest", "pytest", "numpy", "IPython", "matplotlib", "PIL")


def pyinstaller_args(sep: str, onedir: bool) -> list[str]:
    name = "rssi-simulator"
    args = [
        str(ROOT / "main.py"),
        "--name", name,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--icon", str(ROOT / "assets" / "images" / "icon.ico"),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--onedir" if onedir else "--onefile",
    ]
    for d in DATA_DIRS:
        args += ["--add-data", f"{ROOT / d}{sep}{d}"]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    # modules importés dynamiquement par la boucle de jeu
    for hidden in ("ui.screens.main_menu", "ui.screens.org_selection", "ui.screens.dashboard",
                   "ui.screens.incident_room", "ui.screens.ebios_workshop", "ui.screens.audit_screen",
                   "ui.screens.budget_screen", "ui.screens.game_over", "ui.screens.operations",
                   "ui.screens.lobby", "sqlalchemy.dialects.sqlite"):
        args += ["--hidden-import", hidden]
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sep", default=os.pathsep, help="séparateur --add-data (';' Windows, ':' Linux)")
    parser.add_argument("--onedir", action="store_true")
    opts = parser.parse_args()
    if opts.sep not in (";", ":"):
        parser.error("--sep doit valoir ';' ou ':'")
    import PyInstaller.__main__

    PyInstaller.__main__.run(pyinstaller_args(opts.sep, opts.onedir))
    exe = ROOT / "dist" / ("rssi-simulator.exe" if sys.platform == "win32" else "rssi-simulator")
    if exe.exists():
        size = exe.stat().st_size / 1_048_576
        print(f"Exécutable : {exe} ({size:.1f} Mo)")
        if size > 50:
            print("ATTENTION : l'exécutable dépasse l'objectif de 50 Mo", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
