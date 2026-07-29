"""ui_scale → Skalierungsfaktor + QSS-/Pixel-Skalierung (Sprint 68 / Teil B1).

Reine Funktionen (kein Qt-Widget-Zugriff) – analog zu `_geometry.py` (Sprint 67)
unabhängig von der Offscreen-Testplattform mit synthetischen Strings/Zahlen
testbar. `load_scaled_stylesheet` ist der einzige Lade-Pfad für App-Start
(`__main__.main`) und Live-Anwendung (`WorkspaceSession.apply_new_settings`) –
kein zweiter Sonderweg.
"""

from __future__ import annotations

import re
from typing import Final

from sampling_tool.resources import package_resource

# 🔒 Sicherheitslinie (Sprint 68): "normal" MUSS Faktor 1.0 sein – sonst wäre
# das bestehende Aussehen für Bestandsuser nicht mehr byte-identisch.
UI_SCALE_DEFAULT: Final[str] = "normal"

# Faktor-SSOT: die einzige Zuordnung Stufe → Skalierungsfaktor im Projekt.
_SCALE_FACTORS: Final[dict[str, float]] = {
    "klein": 0.9,
    "normal": 1.0,
    "groß": 1.15,
}

UI_SCALE_LEVELS: Final[tuple[str, ...]] = tuple(_SCALE_FACTORS)

_FONT_SIZE_RE: Final[re.Pattern[str]] = re.compile(r"(font-size:\s*)(\d+)(px)")
# Grenzwert-Muster für min/max-width/height – wird NUR innerhalb des per
# `_LOGO_BLOCK_RE` isolierten LogoPlaceholder-Blocks angewendet (siehe unten),
# damit andere Blöcke mit denselben Property-Namen (z. B. der
# QScrollBar::handle-Block mit `min-height`/`min-width`) unangetastet bleiben.
_LOGO_BOUND_RE: Final[re.Pattern[str]] = re.compile(r"((?:min|max)-(?:width|height):\s*)(\d+)(px)")
# Isoliert den `QLabel#LogoPlaceholder { ... }`-Block, damit `_LOGO_BOUND_RE`
# nur dort greift. QSS-Blöcke in dieser Datei sind flach (keine verschachtelten
# `{`), daher fängt ein non-greedy `.*?` mit `re.DOTALL` zuverlässig genau
# einen Block-Body bis zur schließenden `}`.
_LOGO_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(QLabel#LogoPlaceholder\s*\{)(.*?)(\})", re.DOTALL
)


def scale_factor(ui_scale: str) -> float:
    """Stufe → Faktor. Unbekannter Wert fällt sicher auf `normal` zurück."""
    return _SCALE_FACTORS.get(ui_scale, _SCALE_FACTORS[UI_SCALE_DEFAULT])


def scaled_px(base: int, factor: float) -> int:
    """Skaliert einen px-Basiswert und rundet auf ganze Pixel."""
    return round(base * factor)


def scale_stylesheet(qss: str, factor: float) -> str:
    """Skaliert alle `font-size`-Werte + die LogoPlaceholder-Grenzwerte.

    🔒 Sicherheitslinie: bei `factor == 1.0` ist das Ergebnis byte-identisch
    zur Eingabe – `scaled_px(n, 1.0) == n` für jedes `n`, alles andere (Farben,
    Selektoren, Layout-px) wird von den Capture-Gruppen unverändert kopiert.
    """

    def _replace(match: re.Match[str]) -> str:
        prefix, value, suffix = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{scaled_px(int(value), factor)}{suffix}"

    def _replace_logo_block(match: re.Match[str]) -> str:
        prefix, body, suffix = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{_LOGO_BOUND_RE.sub(_replace, body)}{suffix}"

    scaled = _FONT_SIZE_RE.sub(_replace, qss)
    return _LOGO_BLOCK_RE.sub(_replace_logo_block, scaled)


def load_scaled_stylesheet(factor: float) -> str:
    """Lädt `bdo_light.qss` und skaliert es mit `factor`."""
    qss_path = package_resource("ui/styles/bdo_light.qss")
    if not qss_path.exists():
        return ""
    return scale_stylesheet(qss_path.read_text(encoding="utf-8"), factor)
