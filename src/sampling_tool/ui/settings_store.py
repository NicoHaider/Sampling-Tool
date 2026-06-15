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

# Sprint 22 – Kennungen der einzeln schaltbaren Advanced-Sampling-Funktionen.
# Werden im „Ansicht"-Menü als checkbare Einträge geführt und über
# `AppSettings.resolve_feature_visible` aufgelöst.
FEATURE_FILTER: Final[str] = "filter"
FEATURE_CLUSTER: Final[str] = "cluster"
FEATURE_STRATIFIED: Final[str] = "stratified"
SAMPLING_FEATURE_KEYS: Final[tuple[str, ...]] = (
    FEATURE_FILTER,
    FEATURE_CLUSTER,
    FEATURE_STRATIFIED,
)

# Kennungen der persistenten Panel-Toggles (Dashboard / Audit-Trail) – ebenfalls
# im „Ansicht"-Menü geführt, mappen aber auf die bestehenden show_*-Flags.
PANEL_DASHBOARD: Final[str] = "dashboard"
PANEL_AUDIT_TRAIL: Final[str] = "audit_trail"


@dataclass(frozen=True, slots=True)
class SamplingFeatures:
    """Aufgelöste Sichtbarkeit der Advanced-Sampling-Funktionen (Sprint 22).

    Pro Funktion ein Bool, bereits durch `AppSettings.resolve_feature_visible`
    (ODER aus Advanced-Mode + app-weitem Einzel-Toggle) aufgelöst. Der
    `SamplingDialog` rendert ausschließlich anhand dieser Flags – er kennt
    weder `advanced_mode` noch die Einzel-Toggles. Damit lebt die ODER-Logik
    an genau einer Stelle (`resolve_feature_visible`).
    """

    show_filter: bool = False
    show_cluster: bool = False
    show_stratified: bool = False

    @property
    def show_methods(self) -> bool:
        """Methodenwahl-Block sichtbar, sobald Cluster ODER Geschichtet aktiv ist."""
        return self.show_cluster or self.show_stratified

    @property
    def any_advanced(self) -> bool:
        """True, wenn irgendeine Advanced-Funktion sichtbar ist."""
        return self.show_filter or self.show_cluster or self.show_stratified


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
    # Sprint 27: Audit-PDF-Export bietet den von/bis-Datumsfilter nur an, wenn
    # dieser Toggle aktiv ist. Default aus → der Export überspringt den
    # Datumsschritt und exportiert alle Events (bisheriges Verhalten).
    audit_export_offer_date_filter: bool

    # Sichtbare Panels (Allgemein-Tab)
    show_dashboard: bool
    show_audit_trail: bool

    # Erweitert
    advanced_mode: bool
    undo_depth: int
    snapshot_retention_days: int
    log_level: str

    # Einzel-Toggles für Advanced-Sampling-Funktionen (Sprint 22) – app-weit,
    # Default aus. Wirken unabhängig neben `advanced_mode` (ODER-Logik in
    # `resolve_feature_visible`). Steuern die „Ansicht"-Menü-Checkboxen.
    show_filter_feature: bool
    show_cluster_feature: bool
    show_stratified_feature: bool

    # Onboarding
    first_run_completed: bool

    # Sprint 27: app-weiter Sampling-Seed. None = kein fester Seed (es wird
    # weiterhin zufällig gewürfelt und der zuletzt genutzte Seed gemerkt,
    # Sprint-21-Verhalten). Ein gesetzter Seed gilt für die nächste Ziehung;
    # geändert wird er ausschließlich in den Einstellungen (das Seed-Feld im
    # Haupt-Dialog ist schreibgeschützt).
    seed: int | None

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
            audit_export_offer_date_filter=False,
            show_dashboard=True,
            show_audit_trail=True,
            advanced_mode=False,
            undo_depth=DEFAULT_UNDO_DEPTH,
            snapshot_retention_days=DEFAULT_SNAPSHOT_RETENTION_DAYS,
            log_level=DEFAULT_LOG_LEVEL,
            show_filter_feature=False,
            show_cluster_feature=False,
            show_stratified_feature=False,
            first_run_completed=False,
            seed=None,
        )

    # ---- Feature-Sichtbarkeit (Sprint 22) ------------------------------

    def feature_toggle(self, feature: str) -> bool:
        """Reiner Einzel-Toggle-Wert einer Funktion (ohne Advanced-Mode)."""
        if feature == FEATURE_FILTER:
            return self.show_filter_feature
        if feature == FEATURE_CLUSTER:
            return self.show_cluster_feature
        if feature == FEATURE_STRATIFIED:
            return self.show_stratified_feature
        raise ValueError(f"Unbekannte Feature-Kennung: {feature!r}")

    def resolve_feature_visible(self, feature: str) -> bool:
        """Effektive Sichtbarkeit einer Advanced-Funktion.

        ODER-Logik: Advanced Mode (Master) ODER der app-weite Einzel-Toggle.
        Beide Quellen wirken unabhängig – keiner überschreibt den anderen.
        Dies ist die EINZIGE Stelle, an der verodert wird.
        """
        return self.advanced_mode or self.feature_toggle(feature)

    def with_feature_toggle(self, feature: str, enabled: bool) -> AppSettings:
        """Immutable-Update: neues `AppSettings` mit gesetztem Einzel-Toggle."""
        if feature == FEATURE_FILTER:
            return replace(self, show_filter_feature=enabled)
        if feature == FEATURE_CLUSTER:
            return replace(self, show_cluster_feature=enabled)
        if feature == FEATURE_STRATIFIED:
            return replace(self, show_stratified_feature=enabled)
        raise ValueError(f"Unbekannte Feature-Kennung: {feature!r}")

    def resolve_sampling_features(self) -> SamplingFeatures:
        """Bündelt die aufgelöste Sichtbarkeit aller drei Funktionen."""
        return SamplingFeatures(
            show_filter=self.resolve_feature_visible(FEATURE_FILTER),
            show_cluster=self.resolve_feature_visible(FEATURE_CLUSTER),
            show_stratified=self.resolve_feature_visible(FEATURE_STRATIFIED),
        )


def _qsettings() -> QSettings:
    """Ein frisch geöffneter `QSettings`-Handle. Kein App-weiter Singleton,
    weil Qt das selbst sauber synchronisiert."""
    return QSettings(APP_ORG, APP_NAME)


def open_qsettings() -> QSettings:
    """Öffentlicher QSettings-Handle für andere app-weite Stores (Sprint 23).

    Delegiert bewusst an `_qsettings`, damit Tests weiterhin an genau einer
    Stelle (`_qsettings`) isolieren können und `PresetStore` denselben
    Persistenz-Pfad wie `AppSettings` teilt.
    """
    return _qsettings()


def load_settings() -> AppSettings:
    """Lädt die `AppSettings` aus `QSettings`. Fehlende Keys → Defaults.

    Für Bestandsuser ohne `first_run_completed`-Key wird über eine
    Heuristik (eigener Engagement-Ordner oder Default-Ordner existiert)
    entschieden, dass der First-Run-Wizard nicht mehr nötig ist – das
    Flag wird in dem Fall sofort persistiert, damit die Heuristik beim
    nächsten Start nicht erneut greift.
    """
    s = _qsettings()
    base = AppSettings.defaults()

    custom_str = _str(s.value("settings/custom_briefpapier_path", ""))
    custom = Path(custom_str) if custom_str else None

    # Sprint 27: Seed string-persistiert ("" = kein fester Seed, analog
    # custom_briefpapier_path). Ungültige Werte fallen robust auf None zurück.
    seed_str = _str(s.value("settings/seed", ""))
    seed: int | None
    try:
        seed = int(seed_str) if seed_str else None
    except ValueError:
        seed = None

    log_level = _str(s.value("settings/log_level", base.log_level))
    if log_level not in LOG_LEVELS:
        log_level = base.log_level

    has_first_run_key = s.contains("settings/first_run_completed")
    raw_engagements_dir = _str(s.value("settings/engagements_dir", ""))
    if has_first_run_key:
        first_run_completed = _bool(s.value("settings/first_run_completed", False))
    else:
        first_run_completed = _detect_existing_user(raw_engagements_dir, base.engagements_dir)
        if first_run_completed:
            # Migration einmalig persistieren – beim nächsten Start fällt
            # die Heuristik dann nicht mehr ins Gewicht.
            s.setValue("settings/first_run_completed", True)
            s.sync()

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
        audit_export_offer_date_filter=_bool(
            s.value(
                "settings/audit_export_offer_date_filter",
                base.audit_export_offer_date_filter,
            )
        ),
        seed=seed,
        show_dashboard=_bool(s.value("settings/show_dashboard", base.show_dashboard)),
        show_audit_trail=_bool(s.value("settings/show_audit_trail", base.show_audit_trail)),
        advanced_mode=_bool(s.value("settings/advanced_mode", base.advanced_mode)),
        show_filter_feature=_bool(
            s.value("settings/show_filter_feature", base.show_filter_feature)
        ),
        show_cluster_feature=_bool(
            s.value("settings/show_cluster_feature", base.show_cluster_feature)
        ),
        show_stratified_feature=_bool(
            s.value("settings/show_stratified_feature", base.show_stratified_feature)
        ),
        undo_depth=_int(s.value("settings/undo_depth", base.undo_depth), base.undo_depth),
        snapshot_retention_days=_int(
            s.value("settings/snapshot_retention_days", base.snapshot_retention_days),
            base.snapshot_retention_days,
        ),
        log_level=log_level,
        first_run_completed=first_run_completed,
    )


def _detect_existing_user(raw_engagements_dir: str, default_dir: Path) -> bool:
    """Bestandsuser-Heuristik: explizit gesetzter Pfad oder Default-Ordner da."""
    explicit_dir = raw_engagements_dir and raw_engagements_dir != str(default_dir)
    if explicit_dir:
        return True
    return default_dir.exists()


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
    s.setValue(
        "settings/audit_export_offer_date_filter",
        settings.audit_export_offer_date_filter,
    )
    s.setValue("settings/seed", str(settings.seed) if settings.seed is not None else "")
    s.setValue("settings/show_dashboard", settings.show_dashboard)
    s.setValue("settings/show_audit_trail", settings.show_audit_trail)
    s.setValue("settings/advanced_mode", settings.advanced_mode)
    s.setValue("settings/show_filter_feature", settings.show_filter_feature)
    s.setValue("settings/show_cluster_feature", settings.show_cluster_feature)
    s.setValue("settings/show_stratified_feature", settings.show_stratified_feature)
    s.setValue("settings/first_run_completed", settings.first_run_completed)
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
