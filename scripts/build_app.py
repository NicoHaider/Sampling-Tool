"""Cross-platform Build-Script für das Audit Sampling Tool.

Verwendung:
    python scripts/build_app.py            # Build (Mac .app / Windows-Ordner)
    python scripts/build_app.py --dmg      # Mac: zusätzlich .dmg
    python scripts/build_app.py --no-clean # bestehendes dist/ nicht löschen

Nach dem PyInstaller-Lauf startet das Script das gebaute Programm mit
`--self-check build/self_check.json` (Sprint 95) und bricht mit Exit 1 ab, wenn
der Selbsttest rot ist oder keinen Bericht schreibt. `--skip-self-check` nur für
Notfälle.

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

from _script_io import force_utf8_stdout

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Audit Sampling Tool"
SELF_CHECK_REPORT = ROOT / "build" / "self_check.json"
# Der erste Lauf eines frischen Pakets baut den matplotlib-Font-Cache.
SELF_CHECK_TIMEOUT_S = 300


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


def built_executable(dist: Path) -> Path:
    """Pfad des gebauten Programms – das, was der Anwender startet."""
    if platform.system() == "Darwin":
        return dist / f"{APP_NAME}.app" / "Contents" / "MacOS" / "AuditSamplingTool"
    if platform.system() == "Windows":
        return dist / "AuditSamplingTool" / "AuditSamplingTool.exe"
    return dist / "AuditSamplingTool" / "AuditSamplingTool"


def run_self_check(executable: Path, report: Path) -> bool:
    """Startet `executable --self-check report`; True nur bei Exit 0 UND Bericht."""
    print(f"Running self-check on {executable} …")
    report.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [str(executable), "--self-check", str(report)],
            cwd=ROOT,
            timeout=SELF_CHECK_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"✗ Selbsttest konnte nicht ausgeführt werden: {exc}")
        return False
    if not report.exists():
        print(f"✗ Selbsttest hat keinen Bericht geschrieben ({report}), Exit {result.returncode}.")
        return False
    print(report.read_text(encoding="utf-8"))
    if result.returncode != 0:
        print(f"✗ Selbsttest fehlgeschlagen (Exit {result.returncode}).")
        return False
    return True


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
    # Muss vor jeder Ausgabe stehen – insbesondere vor argparse: `--help` geht
    # nach STDOUT (gemessen: 84 Byte stdout, 0 Byte stderr), und `description`
    # ist hier `__doc__`. Ein Sonderzeichen im Modul-Docstring würde also schon
    # `--help` töten, nicht erst den Build. Siehe scripts/_script_io.py.
    force_utf8_stdout()

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
    parser.add_argument(
        "--skip-self-check",
        action="store_true",
        help="Selbsttest des gebauten Programms überspringen (nur für Notfälle)",
    )
    args = parser.parse_args()

    if not args.no_clean:
        clean()

    generate_icons_if_missing()

    dist = run_pyinstaller()

    if args.skip_self_check:
        print("\n! Selbsttest übersprungen (--skip-self-check).")
    elif not run_self_check(built_executable(dist), SELF_CHECK_REPORT):
        print("\n✗ Build abgebrochen: das gebaute Programm besteht den Selbsttest nicht.")
        return 1

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
