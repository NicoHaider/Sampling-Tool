"""User-Settings: Dataclass + `QSettings`-Persistenz.

`AppSettings` ist die einzige Wahrheits-Quelle für globale Anwender-
Präferenzen (Default-Auditor, Engagement-Ordner, Report-Defaults,
Logging-Level). Persistenz geschieht via `QSettings(APP_ORG, APP_NAME)` –
plattform-spezifisch (Plist auf macOS, Registry auf Windows).

Load/Save bewusst stateless: jede Komponente, die das Setting braucht,
ruft `load_settings()`. Schreibvorgang via `save_settings(s)`. Auf
fehlende Keys wird in `defaults()` zurückgefallen, damit ein leerer
QSettings-Store nicht crasht.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from PyQt6.QtCore import QSettings

from sampling_tool.config import APP_NAME, APP_ORG, ENGAGEMENTS_DIR

LOG_LEVELS: Final[tuple[str, ...]] = ("INFO", "DEBUG")
DEFAULT_UNDO_DEPTH: Final[int] = 20
DEFAULT_SNAPSHOT_RETENTION_DAYS: Final[int] = 0  # 0 = unbegrenzt
DEFAULT_LOG_LEVEL: Final[str] = "INFO"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """User-Präferenzen. Immutable – Updates über `replace()`."""

    # Allgemein
    default_auditor_name: str
    engagements_dir: Path

    # Reports
    reset_keeps_filter: bool
    default_include_briefpapier: bool
    default_include_statistics: bool
    custom_briefpapier_path: Path | None

    # Erweitert
    undo_depth: int
    snapshot_retention_days: int
    log_level: str

    @classmethod
    def defaults(cls) -> AppSettings:
        """Werks-Default; wird genutzt, wenn `QSettings` leer ist oder Reset."""
        return cls(
            default_auditor_name="",
            engagements_dir=ENGAGEMENTS_DIR,
            reset_keeps_filter=False,
            default_include_briefpapier=True,
            default_include_statistics=True,
            custom_briefpapier_path=None,
            undo_depth=DEFAULT_UNDO_DEPTH,
            snapshot_retention_days=DEFAULT_SNAPSHOT_RETENTION_DAYS,
            log_level=DEFAULT_LOG_LEVEL,
        )


def _qsettings() -> QSettings:
    """Ein frisch geöffneter `QSettings`-Handle. Kein App-weiter Singleton,
    weil Qt das selbst sauber synchronisiert."""
    return QSettings(APP_ORG, APP_NAME)


def load_settings() -> AppSettings:
    """Lädt die `AppSettings` aus `QSettings`. Fehlende Keys → Defaults."""
    s = _qsettings()
    base = AppSettings.defaults()

    custom_str = _str(s.value("settings/custom_briefpapier_path", ""))
    custom = Path(custom_str) if custom_str else None

    log_level = _str(s.value("settings/log_level", base.log_level))
    if log_level not in LOG_LEVELS:
        log_level = base.log_level

    return replace(
        base,
        default_auditor_name=_str(s.value("settings/default_auditor_name", "")),
        engagements_dir=Path(_str(s.value("settings/engagements_dir", str(base.engagements_dir)))),
        reset_keeps_filter=_bool(s.value("settings/reset_keeps_filter", base.reset_keeps_filter)),
        default_include_briefpapier=_bool(
            s.value("settings/default_include_briefpapier", base.default_include_briefpapier)
        ),
        default_include_statistics=_bool(
            s.value("settings/default_include_statistics", base.default_include_statistics)
        ),
        custom_briefpapier_path=custom,
        undo_depth=_int(s.value("settings/undo_depth", base.undo_depth), base.undo_depth),
        snapshot_retention_days=_int(
            s.value("settings/snapshot_retention_days", base.snapshot_retention_days),
            base.snapshot_retention_days,
        ),
        log_level=log_level,
    )


def save_settings(settings: AppSettings) -> None:
    """Schreibt die `AppSettings` nach `QSettings`."""
    s = _qsettings()
    s.setValue("settings/default_auditor_name", settings.default_auditor_name)
    s.setValue("settings/engagements_dir", str(settings.engagements_dir))
    s.setValue("settings/reset_keeps_filter", settings.reset_keeps_filter)
    s.setValue("settings/default_include_briefpapier", settings.default_include_briefpapier)
    s.setValue("settings/default_include_statistics", settings.default_include_statistics)
    s.setValue(
        "settings/custom_briefpapier_path",
        str(settings.custom_briefpapier_path) if settings.custom_briefpapier_path else "",
    )
    s.setValue("settings/undo_depth", settings.undo_depth)
    s.setValue("settings/snapshot_retention_days", settings.snapshot_retention_days)
    s.setValue("settings/log_level", settings.log_level)
    s.sync()


# ---------------------------------------------------------------------------
# Typ-Helfer – QSettings liefert auf Windows strings, auf macOS native Typen.
# ---------------------------------------------------------------------------


def _str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, int):
        return bool(value)
    return False


def _int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return fallback
    return fallback
