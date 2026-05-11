"""NewEngagementDialog – Validierung & Engagement-Konstruktion."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog

pytestmark = pytest.mark.ui


def _ok_button(dialog: NewEngagementDialog) -> object:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    return box.button(QDialogButtonBox.StandardButton.Ok)


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
