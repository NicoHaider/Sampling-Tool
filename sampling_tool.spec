# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec für das Audit Sampling Tool.

Build:
    pyinstaller sampling_tool.spec --noconfirm
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT / "src"))

APP_NAME = "Audit Sampling Tool"
APP_VERSION = "0.8.0"
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

# Datenfiles bündeln. Die Zielpfade spiegeln die Package-Struktur, weil der
# App-Code Resourcen via `Path(__file__).parent / ...` relativ zu den
# Sub-Modulen lokalisiert (siehe config.py, __main__.py, io/html_report.py).
datas = [
    (
        str(ROOT / "src" / "sampling_tool" / "resources" / "briefpapier"),
        "sampling_tool/resources/briefpapier",
    ),
    (
        str(ROOT / "src" / "sampling_tool" / "resources" / "templates"),
        "sampling_tool/resources/templates",
    ),
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
    # pdfrw + Reportlab-Bridge für Briefpapier-Overlay
    "pdfrw",
    "pdfrw.buildxobj",
    "pdfrw.toreportlab",
    # platformdirs (Recent-Engagements-Store)
    "platformdirs",
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
