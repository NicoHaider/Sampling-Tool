"""Sprint 22 – Einzel-Toggles für Advanced-Sampling-Funktionen.

Deckt die drei Ebenen ab:
1. Settings-Ebene: `AppSettings.resolve_feature_visible` (ODER-Logik aus
   Advanced-Mode + Einzel-Toggle), Persistenz, Defaults.
2. Menü-Ebene: checkbare „Ansicht"-Einträge emittieren Signale, Check-State
   spiegelt die app-weiten Toggles.
3. Controller-/Reproduzierbarkeits-Ebene: Toggle-Handler persistieren
   app-weit, und das Sichtbar-Schalten allein verändert die Stichprobe nicht.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import (
    FEATURE_CLUSTER,
    FEATURE_FILTER,
    FEATURE_STRATIFIED,
    AppSettings,
    load_settings,
    save_settings,
)

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
    bleiben (gleiches Muster wie `test_settings_store`)."""
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            APP_ORG,
            APP_NAME,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Settings-Ebene
# ---------------------------------------------------------------------------


class TestFeatureToggles:
    def test_individual_toggle_shows_feature_without_advanced(self) -> None:
        settings = replace(AppSettings.defaults(), advanced_mode=False, show_filter_feature=True)
        assert settings.resolve_feature_visible(FEATURE_FILTER) is True
        # Andere Funktionen bleiben aus.
        assert settings.resolve_feature_visible(FEATURE_CLUSTER) is False

    def test_advanced_mode_shows_feature_without_individual_toggle(self) -> None:
        settings = replace(AppSettings.defaults(), advanced_mode=True, show_filter_feature=False)
        assert settings.resolve_feature_visible(FEATURE_FILTER) is True

    @pytest.mark.parametrize("advanced", [False, True])
    @pytest.mark.parametrize("individual", [False, True])
    def test_or_logic_either_source_enables(self, advanced: bool, individual: bool) -> None:
        settings = replace(
            AppSettings.defaults(),
            advanced_mode=advanced,
            show_cluster_feature=individual,
        )
        assert settings.resolve_feature_visible(FEATURE_CLUSTER) is (advanced or individual)

    def test_toggling_advanced_does_not_change_individual_state(self) -> None:
        base = replace(
            AppSettings.defaults(),
            show_filter_feature=True,
            show_cluster_feature=False,
            show_stratified_feature=True,
        )
        # Advanced an/aus schalten lässt die Einzel-Toggle-Werte unberührt.
        on = replace(base, advanced_mode=True)
        off = replace(base, advanced_mode=False)
        for variant in (on, off):
            assert variant.show_filter_feature is True
            assert variant.show_cluster_feature is False
            assert variant.show_stratified_feature is True

    def test_toggle_state_persists_app_wide(self) -> None:
        original = replace(
            AppSettings.defaults(),
            show_filter_feature=True,
            show_cluster_feature=False,
            show_stratified_feature=True,
        )
        save_settings(original)
        loaded = load_settings()
        assert loaded.show_filter_feature is True
        assert loaded.show_cluster_feature is False
        assert loaded.show_stratified_feature is True

    def test_default_state(self) -> None:
        # Sprint 36: Filter ist ab Werk sichtbar (unabhängig von Advanced),
        # Cluster/Geschichtet bleiben versteckt.
        defaults = AppSettings.defaults()
        assert defaults.advanced_mode is False
        assert defaults.show_filter_feature is True
        assert defaults.show_cluster_feature is False
        assert defaults.show_stratified_feature is False
        assert defaults.resolve_feature_visible(FEATURE_FILTER) is True
        for feature in (FEATURE_CLUSTER, FEATURE_STRATIFIED):
            assert defaults.resolve_feature_visible(feature) is False

    def test_filter_feature_default_is_true(self) -> None:
        # Sprint 36 – Werks-Default für den Spalten-Filter ist jetzt True.
        assert AppSettings.defaults().show_filter_feature is True

    def test_cluster_and_stratified_defaults_stay_false(self) -> None:
        # Absicherung gegen versehentliches Mit-Umschalten (nur Filter flippt).
        defaults = AppSettings.defaults()
        assert defaults.show_cluster_feature is False
        assert defaults.show_stratified_feature is False

    def test_filter_visible_by_default_without_advanced_mode(self) -> None:
        # ODER-Logik unverändert; der neue Default reicht bereits, damit der
        # Filter ohne Advanced-Mode sichtbar ist.
        defaults = AppSettings.defaults()
        assert defaults.advanced_mode is False
        assert defaults.resolve_feature_visible(FEATURE_FILTER) is True

    def test_load_from_empty_qsettings_yields_filter_true(self) -> None:
        # Fallback-Pfad: leerer QSettings-Store (kein gesetzter Key) → der neue
        # Default schlägt durch, auch für Bestandsuser ohne expliziten Key.
        loaded = load_settings()
        assert loaded.show_filter_feature is True
        # Cluster/Geschichtet bleiben Default aus.
        assert loaded.show_cluster_feature is False
        assert loaded.show_stratified_feature is False

    def test_feature_toggle_returns_raw_individual_value(self) -> None:
        # `feature_toggle` ist der reine Einzel-Toggle (ohne Advanced-Mode).
        settings = replace(AppSettings.defaults(), advanced_mode=True, show_filter_feature=False)
        assert settings.feature_toggle(FEATURE_FILTER) is False
        assert settings.resolve_feature_visible(FEATURE_FILTER) is True

    def test_with_feature_toggle_returns_updated_copy(self) -> None:
        base = AppSettings.defaults()
        updated = base.with_feature_toggle(FEATURE_STRATIFIED, True)
        assert updated.show_stratified_feature is True
        # Original bleibt unverändert (immutable).
        assert base.show_stratified_feature is False

    def test_resolve_unknown_feature_raises(self) -> None:
        with pytest.raises(ValueError, match="Unbekannte Feature-Kennung"):
            AppSettings.defaults().resolve_feature_visible("bogus")

    def test_resolve_sampling_features_packs_all_three(self) -> None:
        settings = replace(
            AppSettings.defaults(),
            advanced_mode=False,
            show_filter_feature=True,
            show_cluster_feature=False,
            show_stratified_feature=True,
        )
        features = settings.resolve_sampling_features()
        assert features.show_filter is True
        assert features.show_cluster is False
        assert features.show_stratified is True
        # `show_methods` ist abgeleitet: Cluster ODER Geschichtet.
        assert features.show_methods is True
        assert features.any_advanced is True


# ---------------------------------------------------------------------------
# 2. Menü-Ebene
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


class TestViewMenu:
    def test_view_menu_has_feature_and_panel_actions(self, window: MainWindow) -> None:
        actions = window._view_menu.actions()
        for action in (
            window._action_feature_filter,
            window._action_feature_cluster,
            window._action_feature_stratified,
            window._action_view_dashboard,
            window._action_view_audit_trail,
        ):
            assert action in actions
            assert action.isCheckable() is True

    def test_feature_actions_default_unchecked(self, window: MainWindow) -> None:
        assert window._action_feature_filter.isChecked() is False
        assert window._action_feature_cluster.isChecked() is False
        assert window._action_feature_stratified.isChecked() is False

    def test_toggling_feature_action_emits_signal(self, window: MainWindow, qtbot: QtBot) -> None:
        with qtbot.waitSignal(window.feature_toggled, timeout=500) as blocker:
            window._action_feature_filter.setChecked(True)
        assert blocker.args == [FEATURE_FILTER, True]

    def test_toggling_panel_action_emits_signal(self, window: MainWindow, qtbot: QtBot) -> None:
        # Bare MainWindow → Action-Default ist unchecked; True löst toggled aus.
        with qtbot.waitSignal(window.panel_toggled, timeout=500) as blocker:
            window._action_view_dashboard.setChecked(True)
        assert blocker.args == ["dashboard", True]

    def test_apply_view_menu_state_sets_checks_without_emitting(self, window: MainWindow) -> None:
        emitted: list[tuple[str, bool]] = []
        window.feature_toggled.connect(lambda key, on: emitted.append((key, on)))
        window.panel_toggled.connect(lambda key, on: emitted.append((key, on)))
        window.apply_view_menu_state(
            show_filter=True,
            show_cluster=False,
            show_stratified=True,
            show_dashboard=False,
            show_audit_trail=True,
        )
        assert window._action_feature_filter.isChecked() is True
        assert window._action_feature_cluster.isChecked() is False
        assert window._action_feature_stratified.isChecked() is True
        assert window._action_view_dashboard.isChecked() is False
        assert window._action_view_audit_trail.isChecked() is True
        # Synchronisieren darf KEIN Toggle-Signal feuern (sonst Schreib-Loop).
        assert emitted == []


# ---------------------------------------------------------------------------
# 3. Controller-Wiring + Reproduzierbarkeit
# ---------------------------------------------------------------------------


@pytest.fixture
def recent_store(tmp_path: Path) -> RecentEngagementsStore:
    return RecentEngagementsStore(path=tmp_path / "recent.json")


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "engagement.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna",
            client_name="ACME",
            auditor_position="Senior",
            audit_type="ISAE 3402",
        )
    )
    assert eng.id is not None
    ds_repo = DatasetRepo(db.connect())
    rows = tuple(
        DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 11)
    )
    dataset = ds_repo.create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        rows,
    )
    assert dataset.id is not None
    db.close()
    return db_path


def _open_dataset(controller: MainController, window: MainWindow, db_path: Path) -> int:
    controller.handle_open_engagement(db_path)
    item = window.sidebar().datasets_widget().item(0)
    assert item is not None
    from PyQt6.QtCore import Qt

    ds_id = item.data(int(Qt.ItemDataRole.UserRole))
    assert isinstance(ds_id, int)
    controller.handle_dataset_selected(ds_id)
    return ds_id


class TestFeatureToggleWiring:
    def test_feature_action_toggle_persists_setting(
        self, window: MainWindow, recent_store: RecentEngagementsStore
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            window._action_feature_filter.setChecked(True)
            assert controller.session.settings.show_filter_feature is True
            # App-weit persistiert.
            assert load_settings().show_filter_feature is True
        finally:
            controller.handle_close_engagement()

    def test_panel_action_toggle_applies_visibility_live(
        self, window: MainWindow, recent_store: RecentEngagementsStore
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            # Dashboard ausblenden über das Menü.
            window._action_view_dashboard.setChecked(False)
            assert controller.session.settings.show_dashboard is False
            assert window._lower_tabs.indexOf(window._dashboard_view) == -1
            assert load_settings().show_dashboard is False
        finally:
            controller.handle_close_engagement()

    def test_init_syncs_menu_from_settings(
        self, window: MainWindow, recent_store: RecentEngagementsStore
    ) -> None:
        settings = replace(
            AppSettings.defaults(), show_filter_feature=True, show_stratified_feature=True
        )
        MainController(window, recent_store=recent_store, settings=settings)
        assert window._action_feature_filter.isChecked() is True
        assert window._action_feature_cluster.isChecked() is False
        assert window._action_feature_stratified.isChecked() is True

    def test_handle_settings_resyncs_menu(
        self, window: MainWindow, recent_store: RecentEngagementsStore
    ) -> None:
        from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog

        defaults = AppSettings.defaults()
        new_settings = replace(defaults, show_dashboard=False)

        class _StubSettingsDialog(SettingsDialog):
            def exec(self) -> int:
                self._result = new_settings
                return int(QDialog.DialogCode.Accepted)

        controller = MainController(
            window,
            recent_store=recent_store,
            settings_dialog_factory=lambda _p, _s: _StubSettingsDialog(defaults),
            settings=defaults,
        )
        controller.help.handle_settings()
        # Menü-Check-State spiegelt die im Dialog geänderte Panel-Sichtbarkeit.
        assert window._action_view_dashboard.isChecked() is False


@contextlib.contextmanager
def _real_sampling_dialog_driver(seeds: list[int], size: int = 3) -> Iterator[None]:
    """Treibt den ECHTEN `SamplingDialog` durch den Controller-Pfad (vgl.
    `test_main_controller._real_sampling_dialog_driver`)."""
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMessageBox

    from sampling_tool.ui.dialogs import sampling_dialog as sd

    def _auto_accept(self: sd.SamplingDialog) -> QDialog.DialogCode:
        self._size_spin.setValue(size)
        self.accept()
        return QDialog.DialogCode.Accepted

    with (
        patch.object(sd, "_generate_random_seed", side_effect=list(seeds)),
        patch.object(sd.SamplingDialog, "exec", _auto_accept),
        patch(
            "sampling_tool.ui.controllers.workspace_controller.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        yield


class TestToggleSamplingNeutrality:
    def test_toggling_feature_availability_does_not_change_results(
        self, window: MainWindow, recent_store: RecentEngagementsStore, populated_db: Path
    ) -> None:
        # Start: Advanced aus, alle Einzel-Toggles aus (= Simple-Mode).
        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            with _real_sampling_dialog_driver(seeds=[111, 222, 333, 444]):
                controller.handle_new_sampling()
                assert controller.session.sample is not None
                first = tuple(controller.session.sample.selected_row_ids)
                seed1 = controller.session.sample.config.seed

                controller.handle_reset_sampling()
                assert controller.session.sample is None

                # Filter-Funktion SICHTBAR schalten – aber KEINEN Filter setzen.
                window._action_feature_filter.setChecked(True)
                assert controller.session.settings.show_filter_feature is True

                controller.handle_new_sampling()
                assert controller.session.sample is not None
                second = tuple(controller.session.sample.selected_row_ids)
                seed2 = controller.session.sample.config.seed

            # Gleicher (gemerkter) Seed + gleiche Größe ⇒ identische Stichprobe.
            assert seed2 == seed1
            assert first == second
            # Nur die Sichtbarkeit wurde geändert – kein Filter ist gesetzt.
            assert controller.session.sample.config.filter_field is None
        finally:
            controller.handle_close_engagement()
