# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec für das Audit Sampling Tool.

Build:
    pyinstaller sampling_tool.spec --noconfirm
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT / "src"))

# Version-SSOT: denselben Wert wie pyproject/Runtime aus `__init__.__version__`
# lesen – kein zweites Versions-Literal im Build. `sampling_tool/__init__.py`
# importiert nichts Schweres (nur `__version__`), der Import ist billig.
from sampling_tool import __version__ as APP_VERSION  # noqa: E402

APP_NAME = "Audit Sampling Tool"
BUNDLE_ID = "at.bdo.audit-sampling-tool"

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

ICON = None
if IS_MAC:
    icns = ROOT / "resources" / "icons" / "app.icns"
    ICON = str(icns) if icns.exists() else None
elif IS_WINDOWS:
    ico = ROOT / "resources" / "icons" / "app.ico"
    ICON = str(ico) if ico.exists() else None

# Datenfiles bündeln. Die Zielpfade matchen den Resource-Resolver in
# `sampling_tool.resources`:
#   - `package_resource("foo/bar")` → `_MEIPASS/sampling_tool/foo/bar`
#   - `shared_resource("foo/bar")`  → `_MEIPASS/resources/foo/bar`
datas = [
    (str(ROOT / "resources"), "resources"),
    (
        str(ROOT / "src" / "sampling_tool" / "persistence" / "migrations"),
        "sampling_tool/persistence/migrations",
    ),
    (
        str(ROOT / "src" / "sampling_tool" / "ui" / "styles"),
        "sampling_tool/ui/styles",
    ),
]

hiddenimports = [
    # matplotlib-Backends
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    # openpyxl interne Helfer
    "openpyxl.cell._writer",
    # reportlab Font-Tabellen (werden lazy geladen)
    "reportlab.rl_settings",
    "reportlab.pdfbase._fontdata_enc_winansi",
    "reportlab.pdfbase._fontdata_enc_macroman",
    "reportlab.pdfbase._fontdata_enc_standard",
    "reportlab.pdfbase._fontdata_enc_symbol",
    "reportlab.pdfbase._fontdata_enc_zapfdingbats",
    "reportlab.pdfbase._fontdata_enc_pdfdoc",
    "reportlab.pdfbase._fontdata_enc_macexpert",
    "reportlab.pdfbase._fontdata_widths_helvetica",
    "reportlab.pdfbase._fontdata_widths_helveticabold",
    "reportlab.pdfbase._fontdata_widths_helveticaoblique",
    "reportlab.pdfbase._fontdata_widths_helveticaboldoblique",
    "reportlab.pdfbase._fontdata_widths_timesroman",
    "reportlab.pdfbase._fontdata_widths_timesbold",
    "reportlab.pdfbase._fontdata_widths_timesitalic",
    "reportlab.pdfbase._fontdata_widths_timesbolditalic",
    "reportlab.pdfbase._fontdata_widths_courier",
    "reportlab.pdfbase._fontdata_widths_courierbold",
    "reportlab.pdfbase._fontdata_widths_courieroblique",
    "reportlab.pdfbase._fontdata_widths_courierboldoblique",
    "reportlab.pdfbase._fontdata_widths_symbol",
    "reportlab.pdfbase._fontdata_widths_zapfdingbats",
    # pypdf: PDF-Briefpapier-Post-Merge (pdf_report._merge_briefpapier_pdf)
    # + Probeparse (briefpapier.validate_briefpapier). Seit Sprint 53
    # Runtime-Dependency (die vorherige PDF-Library ist komplett entfernt).
    "pypdf",
    # platformdirs (Recent-Engagements-Store + Sprint-44-Logging)
    "platformdirs",
    # Sprint 44: RotatingFileHandler-Submodul defensiv explizit (stdlib,
    # wird zwar bereits via direktem `import logging.handlers` in
    # logging_setup.py automatisch erkannt, aber PyInstaller-Analysis
    # bei stdlib-Submodulen ist gelegentlich lückenhaft).
    "logging.handlers",
]

excludes = [
    "tkinter",
    "PyQt5",
    "PySide6",
    "PySide2",
    "pytest",
    "pytest_qt",
]

a = Analysis(
    ["src/sampling_tool/__main__.py"],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AuditSamplingTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AuditSamplingTool",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier=BUNDLE_ID,
        version=APP_VERSION,
        info_plist={
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSPrincipalClass": "NSApplication",
        },
    )
