"""NewEngagementDialog – Validierung & Engagement-Konstruktion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog

pytestmark = pytest.mark.ui


def _ok_button(dialog: NewEngagementDialog) -> object:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    return box.button(QDialogButtonBox.StandardButton.Ok)


def _capture_suggested_path(dialog: NewEngagementDialog) -> str:
    """Ruft `_on_accept` mit gemocktem `QFileDialog` und liefert den
    vorgeschlagenen Default-Pfad (das 3. Argument von `getSaveFileName`)."""
    captured: dict[str, str] = {}

    def _fake_save(parent: object, caption: str, directory: str, filt: str) -> tuple[str, str]:
        captured["directory"] = directory
        return ("", "")  # User-Cancel → `_on_accept` bricht danach ab

    with patch(
        "sampling_tool.ui.dialogs.new_engagement_dialog.QFileDialog.getSaveFileName",
        side_effect=_fake_save,
    ):
        dialog._on_accept()
    return captured["directory"]


class TestNewEngagementDialog:
    def test_ok_disabled_when_fields_empty(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        # Default-Auditor-Name aus dem OS – Position+Client leer.
        ok = _ok_button(dialog)
        assert ok.isEnabled() is False  # type: ignore[attr-defined]

    def test_ok_enabled_after_all_required_set(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Anna Auditorin")
        dialog._auditor_position.setText("Senior Auditor")
        dialog._client_name.setText("ACME GmbH")
        assert _ok_button(dialog).isEnabled() is True  # type: ignore[attr-defined]

    def test_get_engagement_returns_filled_model(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Anna")
        dialog._auditor_position.setText("Senior")
        dialog._client_name.setText("ACME")
        dialog._audit_type_combo.setCurrentText("IDW PS 951")
        eng = dialog.get_engagement()
        assert eng.auditor_name == "Anna"
        assert eng.auditor_position == "Senior"
        assert eng.client_name == "ACME"
        assert eng.audit_type == "IDW PS 951"

    def test_audit_type_sonstige_uses_freetext(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("A")
        dialog._auditor_position.setText("P")
        dialog._client_name.setText("C")
        dialog._audit_type_combo.setCurrentText("Sonstige")
        # Solange Freitext leer, bleibt OK disabled.
        assert _ok_button(dialog).isEnabled() is False  # type: ignore[attr-defined]
        dialog._audit_type_other.setText("Forensische Sonderprüfung")
        assert _ok_button(dialog).isEnabled() is True  # type: ignore[attr-defined]
        assert dialog.get_engagement().audit_type == "Forensische Sonderprüfung"

    def test_get_db_path_raises_before_accept(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        with pytest.raises(RuntimeError):
            dialog.get_db_path()


class TestDefaultFilenameWithAuditType:
    """Sprint 30: der vorgeschlagene Default-Dateiname enthält die Prüfungsart,
    damit zwei Projekte desselben Mandanten mit unterschiedlicher Prüfungsart
    nicht kollidieren. `sanitize_for_path` wird wiederverwendet."""

    def test_default_filename_includes_sanitized_audit_type(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        dialog = NewEngagementDialog(engagements_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Anna")
        dialog._auditor_position.setText("Senior")
        dialog._client_name.setText("ACME GmbH")
        dialog._audit_type_combo.setCurrentText("ISAE 3402 Typ 2")

        name = Path(_capture_suggested_path(dialog)).name

        # Exaktes Format <sanitize(mandant)>_<sanitize(prüfungstyp)>.db (Spec 2a):
        # „ACME GmbH" → „ACME_GmbH", „ISAE 3402 Typ 2" → „ISAE_3402_Typ_2".
        assert name == "ACME_GmbH_ISAE_3402_Typ_2.db"
        assert " " not in name
        assert "/" not in name

    def test_other_freetext_audit_type_in_filename(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = NewEngagementDialog(engagements_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Anna")
        dialog._auditor_position.setText("Senior")
        dialog._client_name.setText("ACME")
        dialog._audit_type_combo.setCurrentText("Sonstige")
        dialog._audit_type_other.setText("Forensische Sonderprüfung")

        name = Path(_capture_suggested_path(dialog)).name

        # Umlaut-Transliteration (ü→ue) + Leerzeichen→`_` aus `sanitize_for_path`;
        # die Reihenfolge <mandant>_<prüfungstyp>.db wird exakt geprüft.
        assert name == "ACME_Forensische_Sonderpruefung.db"
        assert " " not in name
        assert "/" not in name

    def test_empty_audit_type_falls_back_to_client_only(self, qtbot: QtBot) -> None:
        dialog = NewEngagementDialog()
        qtbot.addWidget(dialog)
        # „Sonstige" ohne Freitext → `_selected_audit_type()` ist leer.
        dialog._audit_type_combo.setCurrentText("Sonstige")
        assert dialog._selected_audit_type() == ""
        # Defensiver Fallback: kein `_`-Anhängsel ohne Inhalt.
        assert dialog._default_target_name("ACME") == "ACME.db"
