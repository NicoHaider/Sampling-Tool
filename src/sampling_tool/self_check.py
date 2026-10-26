"""Selbsttest des ausgelieferten Pakets (`--self-check`, Sprint 95).

Prüft funktional, dass die Komponenten im Paket liegen, die erst bei Bedarf
importiert werden (Pillow, pypdf, reportlab, matplotlib, openpyxl, calamine,
PyQt6), und dass der RNG-Vertrag im Paket dieselbe Ziehung liefert wie im
Quellcode. Ein fehlendes Modul dieser Art fällt beim reinen Programmstart nicht
auf – der Build- und der Release-Smoke führen deshalb diesen Selbsttest auf dem
gebauten bzw. entpackten Programm aus.

Bewusst ohne `QApplication`, Netzwerk, QSettings, Projektdatei oder
Logging-Setup der App; geschrieben wird nur in ein eigenes Temp-Verzeichnis.
Alle schweren Importe stehen lazy in den Checks, damit der normale App-Start
dieses Modul nichts kostet.
"""

from __future__ import annotations

import binascii
import io
import json
import os
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

SELF_CHECK_FLAG: Final[str] = "--self-check"

# Simple-Ziehung aus `tests/unit/test_golden_vectors.py` (`GOLDEN_SIMPLE[42]`,
# size=15 aus row_ids 1..60). `test_self_check.py` prüft die Gleichheit mit dem
# Golden-Vektor per Import – hier darf sich nichts unabhängig davon ändern.
RNG_SEED: Final[int] = 42
RNG_POPULATION: Final[int] = 60
RNG_SIZE: Final[int] = 15
RNG_EXPECTED: Final[tuple[int, ...]] = (1, 8, 9, 10, 12, 16, 17, 32, 33, 41, 43, 51, 52, 53, 57)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Ergebnis eines einzelnen Checks; `detail` nennt Version bzw. Fehler."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SelfCheckReport:
    """Gesamtergebnis: `ok` nur, wenn jeder einzelne Check grün ist."""

    ok: bool
    checks: tuple[CheckResult, ...]

    def to_json(self) -> str:
        from sampling_tool import __version__
        from sampling_tool.resources import is_frozen

        payload = {
            "ok": self.ok,
            "version": __version__,
            "frozen": is_frozen(),
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "checks": [asdict(check) for check in self.checks],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Checks – jeder liefert bei Erfolg ein Detail und wirft bei Misserfolg
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int) -> bytes:
    """Minimales RGB-PNG ohne Pillow – der Briefpapier-Check soll an der
    Validierung scheitern, wenn Pillow fehlt, nicht schon beim Erzeugen."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xc8\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _check_pillow(_tmp: Path) -> str:
    import PIL
    from PIL import Image

    for fmt in ("PNG", "JPEG"):
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), color=(200, 0, 0)).save(buffer, format=fmt)
        buffer.seek(0)
        with Image.open(buffer) as img:
            img.load()
            if img.format != fmt or img.size != (2, 2):
                raise RuntimeError(f"{fmt} kam als {img.format} {img.size} zurück")
    return f"Pillow {PIL.__version__}: PNG und JPEG geschrieben und gelesen"


def _check_briefpapier(tmp: Path) -> str:
    from sampling_tool.config import DEFAULT_BRIEFPAPIER
    from sampling_tool.io.briefpapier import validate_briefpapier

    validate_briefpapier(DEFAULT_BRIEFPAPIER)
    png = tmp / "briefpapier.png"
    png.write_bytes(_png_bytes(4, 4))
    validate_briefpapier(png)
    return f"{DEFAULT_BRIEFPAPIER.name} und PNG validiert"


def _check_pypdf(_tmp: Path) -> str:
    import pypdf

    from sampling_tool.config import DEFAULT_BRIEFPAPIER

    pages = len(pypdf.PdfReader(str(DEFAULT_BRIEFPAPIER)).pages)
    if pages < 1:
        raise RuntimeError(f"{DEFAULT_BRIEFPAPIER.name} hat keine Seiten")
    return f"pypdf {pypdf.__version__}: {DEFAULT_BRIEFPAPIER.name} mit {pages} Seite(n)"


def _check_reportlab(_tmp: Path) -> str:
    import reportlab
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen.canvas import Canvas

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=landscape(A4))
    canvas.drawString(72, 72, "Selbsttest")
    canvas.save()
    if not buffer.getvalue().startswith(b"%PDF"):
        raise RuntimeError("reportlab hat kein PDF erzeugt")
    return f"reportlab {reportlab.Version}: PDF mit {len(buffer.getvalue())} Byte"


def _check_matplotlib(_tmp: Path) -> str:
    import matplotlib

    from sampling_tool.io.charts import render_bar_chart_bytes

    png = render_bar_chart_bytes(["A", "B"], [1.0, 2.0], title="Selbsttest")
    if not png.startswith(b"\x89PNG"):
        raise RuntimeError("matplotlib hat kein PNG erzeugt")
    return f"matplotlib {matplotlib.__version__}: Chart mit {len(png)} Byte"


def _check_xlsx_roundtrip(_tmp: Path) -> str:
    import openpyxl
    from python_calamine import CalamineWorkbook

    expected = [["Konto", "Betrag"], ["4711", 12.5]]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("openpyxl hat kein aktives Sheet angelegt")
    for row in expected:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    rows = CalamineWorkbook.from_filelike(buffer).get_sheet_by_index(0).to_python()
    if rows != expected:
        raise RuntimeError(f"calamine las {rows!r} statt {expected!r}")
    return f"openpyxl {openpyxl.__version__} geschrieben, calamine gelesen"


def _check_rng_contract(_tmp: Path) -> str:
    from sampling_tool.core.models import DatasetRow, SampleConfig, SamplingMethod
    from sampling_tool.core.rng import SAMPLING_ALGORITHM_VERSION
    from sampling_tool.core.sampling import SimpleSampler

    config = SampleConfig(method=SamplingMethod.SIMPLE, size=RNG_SIZE, seed=RNG_SEED)
    rows = (DatasetRow(row_id=i, values={}) for i in range(1, RNG_POPULATION + 1))
    selected = SimpleSampler(config).sample(rows).selected_row_ids
    if selected != RNG_EXPECTED:
        raise RuntimeError(f"Seed {RNG_SEED} zog {selected!r} statt {RNG_EXPECTED!r}")
    return f"{SAMPLING_ALGORITHM_VERSION}: Seed {RNG_SEED} zieht den Golden-Vektor"


def _check_pyqt(_tmp: Path) -> str:
    from PyQt6 import QtCore, QtGui, QtWidgets

    del QtGui, QtWidgets
    return f"PyQt6 {QtCore.PYQT_VERSION_STR}, Qt {QtCore.QT_VERSION_STR}"


CHECKS: Final[tuple[tuple[str, Callable[[Path], str]], ...]] = (
    ("pillow", _check_pillow),
    ("briefpapier", _check_briefpapier),
    ("pypdf", _check_pypdf),
    ("reportlab", _check_reportlab),
    ("matplotlib", _check_matplotlib),
    ("xlsx", _check_xlsx_roundtrip),
    ("rng", _check_rng_contract),
    ("pyqt6", _check_pyqt),
)


def _run_one(name: str, check: Callable[[Path], str], tmp: Path) -> CheckResult:
    try:
        return CheckResult(name=name, ok=True, detail=check(tmp))
    except Exception as exc:  # jeder Fehler ist ein Befund, keiner bricht die übrigen ab
        return CheckResult(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")


def run_self_check() -> SelfCheckReport:
    """Führt alle Checks aus; ein roter Check stoppt die übrigen nicht."""
    with tempfile.TemporaryDirectory(prefix="sampling-self-check-") as tmp:
        results = tuple(_run_one(name, check, Path(tmp)) for name, check in CHECKS)
    return SelfCheckReport(ok=all(r.ok for r in results), checks=results)


def run_entry(report_path: Path) -> int:
    """Einstieg für `--self-check <pfad>`: Bericht als JSON nach `report_path`.

    In eine Datei statt nach stdout, weil das Windows-Paket `console=False` hat
    und stdout dort verloren geht. 0 = alles grün, 1 = mindestens ein Check
    rot, 2 = der Bericht ließ sich nicht schreiben.

    matplotlib legt beim ersten Import seinen Font-Cache im Benutzerprofil an;
    im eigenen Prozess des Selbsttests landet er im Temp-Verzeichnis.
    """
    with tempfile.TemporaryDirectory(prefix="sampling-self-check-mpl-") as mpl_dir:
        os.environ.setdefault("MPLCONFIGDIR", mpl_dir)
        report = run_self_check()
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8")
    except OSError as exc:
        print(f"Self-check report could not be written to {report_path}: {exc}")
        return 2
    failed = [check.name for check in report.checks if not check.ok]
    if failed:
        print(f"Self-check FAILED ({', '.join(failed)}), report: {report_path}")
        return 1
    print(f"Self-check OK ({len(report.checks)} checks), report: {report_path}")
    return 0
