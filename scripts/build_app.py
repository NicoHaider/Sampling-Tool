"""Cross-platform Build-Script für das Audit Sampling Tool.

Verwendung:
    python scripts/build_app.py            # Build (Mac .app / Windows-Ordner)
    python scripts/build_app.py --dmg      # Mac: zusätzlich .dmg
    python scripts/build_app.py --no-clean # bestehendes dist/ nicht löschen

Voraussetzungen:
    pip install -e ".[build]"
    Optional auf Mac für DMG: brew install create-dmg
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Audit Sampling Tool"


def clean() -> None:
    """Entfernt vorherige Build-Artefakte."""
    for directory in ("build", "dist"):
        path = ROOT / directory
        if path.exists():
            print(f"Removing {path}")
            shutil.rmtree(path)


def generate_icons_if_missing() -> None:
    """Erzeugt Platzhalter-Icons, falls noch keine existieren."""
    icons_dir = ROOT / "resources" / "icons"
    if icons_dir.exists() and any(icons_dir.glob("icon_*.png")):
        return
    print("Generating placeholder icons …")
    subprocess.run(
        [sys.executable, "scripts/generate_app_icon.py"],
        check=True,
        cwd=ROOT,
    )


def run_pyinstaller() -> Path:
    """Ruft PyInstaller mit der Spec-Datei auf und gibt den dist-Ordner zurück."""
    print("Running PyInstaller …")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "sampling_tool.spec", "--noconfirm"],
        check=True,
        cwd=ROOT,
    )
    return ROOT / "dist"


def make_dmg() -> Path | None:
    """Erzeugt ein DMG aus dem .app-Bundle (nur macOS, benötigt `create-dmg`)."""
    if platform.system() != "Darwin":
        print("DMG-Erzeugung nur auf macOS möglich.")
        return None

    if not shutil.which("create-dmg"):
        print("create-dmg nicht installiert. Installiere via: brew install create-dmg")
        print("Überspringe DMG-Erzeugung.")
        return None

    app_path = ROOT / "dist" / f"{APP_NAME}.app"
    if not app_path.exists():
        print(f"App-Bundle nicht gefunden: {app_path}")
        return None

    dmg_path = ROOT / "dist" / "AuditSamplingTool.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    subprocess.run(
        [
            "create-dmg",
            "--volname",
            APP_NAME,
            "--window-size",
            "600",
            "400",
            "--icon-size",
            "100",
            "--app-drop-link",
            "450",
            "200",
            str(dmg_path),
            str(app_path),
        ],
        check=True,
    )
    return dmg_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dmg",
        action="store_true",
        help="Mac: zusätzlich .dmg erzeugen (benötigt create-dmg)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="dist/ und build/ NICHT vor dem Build löschen",
    )
    args = parser.parse_args()

    if not args.no_clean:
        clean()

    generate_icons_if_missing()

    dist = run_pyinstaller()

    print("\n✓ Build erfolgreich.")
    print(f"  Output: {dist}")

    if args.dmg:
        dmg = make_dmg()
        if dmg is not None:
            print(f"  DMG:    {dmg}")

    if platform.system() == "Darwin":
        print(f'\nMac: "{APP_NAME}.app" nach /Applications kopieren oder doppelklicken.')
    elif platform.system() == "Windows":
        print("\nWindows: Ordner 'AuditSamplingTool/' enthält 'AuditSamplingTool.exe'.")
    else:
        print("\nLinux: nicht offiziell unterstützt – nur Mac und Windows sind Zielplattformen.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
