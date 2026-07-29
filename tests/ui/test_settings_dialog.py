"""Tests für `SettingsDialog`: Tabs laden, Reset, Result-Konstruktion."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QMessageBox, QScrollArea
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
from sampling_tool.ui.settings_store import AppSettings, load_settings, save_settings

pytestmark = pytest.mark.ui


@pytest.fixture
def defaults() -> AppSettings:
    return AppSettings.defaults()


class TestBdoDefaultDropdowns:
    """Sprint 33: zwei Standard-Dropdowns (BDO-Gesellschaft + Standort)."""

    def test_leere_keys_zeigen_default(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._bdo_company.currentData() == "austria_gmbh"
        assert dialog._bdo_location.currentData() == "wien"

    def test_dropdowns_laden_aktuelle_keys(self, qtbot: QtBot) -> None:
        current = replace(
            AppSettings.defaults(),
            bdo_company_key="consulting_gmbh",
            bdo_location_key="linz",
        )
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._bdo_company.currentData() == "consulting_gmbh"
        assert dialog._bdo_location.currentData() == "linz"

    def test_accept_speichert_gewaehlte_keys(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._bdo_company.setCurrentIndex(dialog._bdo_company.findData("audit_gmbh"))
        dialog._bdo_location.setCurrentIndex(dialog._bdo_location.findData("graz"))
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.bdo_company_key == "audit_gmbh"
        assert result.bdo_location_key == "graz"


class TestSettingsDialog:
    def test_dialog_constructs_with_defaults(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._auditor_name.text() == ""
        assert dialog._radio_placeholder.isChecked()
        assert dialog._reset_keeps_filter.isChecked() is False
        assert dialog._default_briefpapier.isChecked() is True

    def test_dialog_loads_current_values(self, qtbot: QtBot, tmp_path: Path) -> None:
        custom = tmp_path / "custom.pdf"
        custom.write_bytes(b"%PDF-1.4\n")
        current = replace(
            AppSettings.defaults(),
            default_auditor_name="Bob",
            custom_briefpapier_path=custom,
            undo_depth=11,
            log_level="DEBUG",
        )
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._auditor_name.text() == "Bob"
        assert dialog._radio_custom.isChecked()
        assert dialog._custom_briefpapier.text() == str(custom)
        assert dialog._undo_depth.value() == 11
        assert dialog._log_level.currentText() == "DEBUG"

    def test_get_settings_returns_none_before_accept(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog.get_settings() is None

    def test_accept_produces_result_with_form_values(
        self, qtbot: QtBot, defaults: AppSettings, tmp_path: Path
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Carla")
        dialog._engagements_dir.setText(str(tmp_path / "eng"))
        dialog._reset_keeps_filter.setChecked(True)
        dialog._undo_depth.setValue(30)
        idx = dialog._log_level.findText("DEBUG")
        dialog._log_level.setCurrentIndex(idx)

        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.default_auditor_name == "Carla"
        assert result.engagements_dir == tmp_path / "eng"
        assert result.reset_keeps_filter is True
        assert result.undo_depth == 30
        assert result.log_level == "DEBUG"

    def test_accept_with_empty_engagements_dir_does_not_close(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._engagements_dir.setText("")
        called: list[bool] = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: called.append(True))

        dialog._on_accept()
        assert called == [True]
        assert dialog.get_settings() is None

    def test_reset_button_restores_defaults(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(
            defaults,
            default_auditor_name="Z",
            undo_depth=99,
            reset_keeps_filter=True,
        )
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._auditor_name.text() == ""
        assert dialog._undo_depth.value() == defaults.undo_depth
        assert dialog._reset_keeps_filter.isChecked() is False

    def test_custom_radio_disables_when_placeholder_selected(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._radio_placeholder.setChecked(True)
        dialog._on_accept()
        # leerer Pfad bei Placeholder-Modus → custom_briefpapier_path None.
        assert dialog.get_settings() is not None
        assert dialog.get_settings().custom_briefpapier_path is None  # type: ignore[union-attr]

    def test_cancel_keeps_result_none(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.get_settings() is None


class TestAdvancedModeToggle:
    def test_checkbox_shows_initial_value(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._chk_advanced_mode.isChecked() is False

    def test_checkbox_prefilled_when_enabled(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, advanced_mode=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._chk_advanced_mode.isChecked() is True

    def test_ok_propagates_advanced_mode(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._chk_advanced_mode.setChecked(True)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.advanced_mode is True

    def test_reset_to_defaults_unchecks_advanced(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, advanced_mode=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._chk_advanced_mode.isChecked() is False


class TestAuditExportDateFilterToggle:
    """Sprint 27: Reports-Tab-Checkbox für den Audit-Export-Datumsfilter."""

    def test_default_unchecked(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._audit_export_date_filter.isChecked() is False

    def test_prefilled_when_enabled(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, audit_export_offer_date_filter=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._audit_export_date_filter.isChecked() is True

    def test_ok_propagates(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._audit_export_date_filter.setChecked(True)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.audit_export_offer_date_filter is True

    def test_reset_restores_default(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, audit_export_offer_date_filter=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._audit_export_date_filter.isChecked() is False


class TestSeedSettingField:
    """Sprint 27: Seed wird ausschließlich in den Einstellungen geändert."""

    def test_default_shows_random(self, qtbot: QtBot, defaults: AppSettings) -> None:
        # seed=None → SpinBox steht auf 0 (specialValueText „zufällig").
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._seed_spin.value() == 0

    def test_prefilled_with_seed(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, seed=12345)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._seed_spin.value() == 12345

    def test_seed_editable_in_settings(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        # Das Feld ist hier editierbar (anders als im Haupt-Dialog).
        assert dialog._seed_spin.isReadOnly() is False
        dialog._seed_spin.setValue(777)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.seed == 777

    def test_zero_means_random(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, seed=42)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(0)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.seed is None

    def test_dice_sets_positive_seed(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._seed_dice.click()
        assert dialog._seed_spin.value() > 0

    def test_reset_restores_random(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, seed=5)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._seed_spin.value() == 0


class TestPanelVisibilityToggle:
    def test_dialog_zeigt_panel_checkboxen_mit_defaults(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_dashboard.isChecked() is True
        assert dialog._chk_show_audit_trail.isChecked() is True

    def test_dialog_prefilled_panel_flags(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, show_dashboard=False, show_audit_trail=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_dashboard.isChecked() is False
        assert dialog._chk_show_audit_trail.isChecked() is True

    def test_ok_propagates_panel_flags(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._chk_show_dashboard.setChecked(False)
        dialog._chk_show_audit_trail.setChecked(False)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.show_dashboard is False
        assert result.show_audit_trail is False

    def test_reset_to_defaults_restores_panel_flags(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, show_dashboard=False, show_audit_trail=False)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._chk_show_dashboard.isChecked() is True
        assert dialog._chk_show_audit_trail.isChecked() is True


class TestShowSampleIdColumnSetting:
    """Sprint 31: app-weiter Toggle „ID in Stichprobenliste anzeigen" (Default an)."""

    def test_show_sample_id_column_default_true(self) -> None:
        assert AppSettings.defaults().show_sample_id_column is True

    def test_dialog_checkbox_reflects_default(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_sample_id_column.isChecked() is True

    def test_dialog_prefilled_when_disabled(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, show_sample_id_column=False)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_sample_id_column.isChecked() is False

    def test_ok_propagates(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._chk_show_sample_id_column.setChecked(False)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.show_sample_id_column is False

    def test_reset_restores_default_true(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, show_sample_id_column=False)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._chk_show_sample_id_column.isChecked() is True


class TestShowSampleIdColumnRoundtrip:
    """Sprint 31: show_sample_id_column übersteht QSettings-Save/Load."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.settings_store._qsettings",
            lambda: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
            ),
        )

    def test_roundtrip_save_load(self) -> None:
        save_settings(replace(AppSettings.defaults(), show_sample_id_column=False))
        assert load_settings().show_sample_id_column is False
        save_settings(replace(AppSettings.defaults(), show_sample_id_column=True))
        assert load_settings().show_sample_id_column is True

    def test_missing_key_falls_back_to_default_true(self) -> None:
        # Leerer Store (kein Key geschrieben) → Default True.
        assert load_settings().show_sample_id_column is True


class TestLogFileInfoText:
    def test_info_label_shows_central_log_path_not_project_folder(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from PyQt6.QtWidgets import QLabel

        fake_path = tmp_path / "fake" / "app.log"
        monkeypatch.setattr(
            "sampling_tool.ui.dialogs.settings_dialog.log_file_path",
            lambda: fake_path,
        )
        dialog = SettingsDialog(AppSettings.defaults())
        qtbot.addWidget(dialog)
        all_text = " ".join(
            child.text() for child in dialog.findChildren(QLabel) if hasattr(child, "text")
        )
        assert str(fake_path) in all_text
        assert "Projekt-Ordner unter" not in all_text


def _make_png(path: Path) -> Path:
    """Schreibt ein winziges, gültiges 1×1-PNG für die Tests."""
    payload = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
        b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x03\x05\x00\x01\x01\x00"
        b"\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    path.write_bytes(payload)
    return path


class TestBrowseBriefpapierValidation:
    """Sprint 47 / N-010: Fail-Fast-Validierung beim Auswählen im Dialog."""

    def test_rejects_corrupt_pdf_and_does_not_set_path(
        self, qtbot: QtBot, defaults: AppSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.4\nnot a real xref table, just garbage\n")
        monkeypatch.setattr(
            "sampling_tool.ui.dialogs.settings_dialog.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(corrupt), ""),
        )
        warnings: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda _self, _title, text, *a, **k: warnings.append(text),
        )

        dialog._on_browse_briefpapier()

        assert dialog._custom_briefpapier.text() == ""
        assert dialog._radio_custom.isChecked() is False
        assert len(warnings) == 1

    def test_accepts_valid_png_and_sets_path(
        self, qtbot: QtBot, defaults: AppSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        png = _make_png(tmp_path / "letter.png")
        monkeypatch.setattr(
            "sampling_tool.ui.dialogs.settings_dialog.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(png), ""),
        )

        dialog._on_browse_briefpapier()

        assert dialog._custom_briefpapier.text() == str(png)
        assert dialog._radio_custom.isChecked() is True

    def test_manually_typed_corrupt_path_is_rejected_on_accept(
        self, qtbot: QtBot, defaults: AppSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sprint 47 / N-010 hard constraint: eine unlesbare Datei darf NIE
        gespeichert werden – auch wenn sie manuell ins Textfeld getippt
        statt über den Datei-Dialog ausgewählt wurde."""
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.4\nnot a real xref table, just garbage\n")
        dialog._custom_briefpapier.setText(str(corrupt))
        dialog._radio_custom.setChecked(True)
        warnings: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda _self, _title, text, *a, **k: warnings.append(text),
        )

        dialog._on_accept()

        assert dialog.get_settings() is None
        assert len(warnings) == 1


class TestSnapshotRetentionRemoved:
    """Sprint 57 / L-002: totes UI-Feld ohne Produktpfad-Wirkung entfernt."""

    def test_snapshot_retention_removed(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_snapshot_retention")


class TestScrollFallback:
    """Sprint 67 / Teil A: Inhalt scrollt, OK/Abbrechen bleiben immer sichtbar."""

    def test_scroll_area_wraps_content_buttons_stay_outside(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        scroll_areas = dialog.findChildren(QScrollArea)
        assert scroll_areas
        for scroll in scroll_areas:
            assert not scroll.isAncestorOf(dialog._buttons)

    def test_height_is_clamped_to_available_screen(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        screen = dialog.screen()
        assert screen is not None
        assert dialog.maximumHeight() <= screen.availableGeometry().height()

    def test_settings_hint_labels_not_clipped(self, qtbot: QtBot, defaults: AppSettings) -> None:
        """Sprint 69 / Bug 2: Wortumbruch-Hinweise wurden bei der `QScrollArea`
        aus Sprint 67 einzeilig gerendert und dadurch abgeschnitten/überlappten
        die nächste Formularzeile. Fix: `_WrappingHintLabel` hält die
        Mindesthöhe passend zur Wortumbruch-Höhe bei der aktuellen Breite.
        """
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        # Erzwingt die kleinste zulässige Dialogbreite (`setMinimumWidth`)
        # statt der evtl. größeren sizeHint-Breite, weil genau dort am
        # wenigsten Platz für den Wortumbruch ist.
        dialog.resize(dialog.minimumWidth(), dialog.height())
        dialog.show()
        qtbot.waitExposed(dialog)
        # Der "Erweitert"-Tab (Index 2) ist beim Öffnen nicht die aktive
        # Tab-Seite; `QTabWidget` layoutet inaktive Seiten nicht, bevor sie
        # zum ersten Mal sichtbar werden – genau bei diesem ersten Layout-Pass
        # trat der Clipping-Bug auf.
        dialog._tabs.setCurrentIndex(2)
        qtbot.wait(50)

        for label in (dialog._ui_scale_hint, dialog._info_label):
            # 1) Bei der Breite, die das reale Layout gerade zuweist.
            width = label.width()
            assert label.height() >= label.heightForWidth(width), (
                f"{label.text()!r}: height={label.height()} "
                f"< heightForWidth({width})={label.heightForWidth(width)}"
            )

            # 2) Zusätzlich explizit bei einer schmalen Breite: Die im
            # Offscreen-Test verwendete Ersatzschrift ist deutlich schmaler
            # als reale Desktop-Schriften, außerdem zieht der breitere
            # "Reports"-Tab die gemeinsame `QTabWidget`-Breite hoch (Qt
            # bemisst sie an der breitesten Tab-Seite, nicht an der gerade
            # aktiven) – auf einem echten Bildschirm mit realer Schrift wird
            # trotzdem mehrzeilig umgebrochen. Ein direktes Resize auf eine
            # schmale Breite bildet das nach und prüft den eigentlichen
            # Mechanismus (Mindesthöhe folgt `heightForWidth` bei JEDER
            # Breite), unabhängig von Font-Metriken der Testumgebung.
            narrow_width = 300
            label.resize(narrow_width, label.height())
            qtbot.wait(10)
            assert label.height() >= label.heightForWidth(narrow_width), (
                f"{label.text()!r} @ {narrow_width}px: height={label.height()} "
                f"< heightForWidth({narrow_width})={label.heightForWidth(narrow_width)}"
            )


class TestUiScaleSetting:
    """Sprint 68 / Teil B1: UI-Größe-Dropdown im Erweitert-Tab."""

    def test_default_shows_normal(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._ui_scale.currentData() == "normal"

    def test_prefilled_with_current_value(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, ui_scale="groß")
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._ui_scale.currentData() == "groß"

    def test_ok_propagates(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._ui_scale.setCurrentIndex(dialog._ui_scale.findData("klein"))
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.ui_scale == "klein"

    def test_reset_restores_normal(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, ui_scale="groß")
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._ui_scale.currentData() == "normal"
