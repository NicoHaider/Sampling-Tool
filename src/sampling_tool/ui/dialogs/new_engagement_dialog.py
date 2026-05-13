"""Modal-Dialog für die Anlage eines neuen Engagements.

Pflichtfelder gemäß altem VBA-Sheet „Eingabe KDaten":
- Auditor-Name (vorausgefüllt aus dem OS-Login)
- Auditor-Position
- Mandant (Kunde)
- Prüfungstyp (ComboBox mit Default-Werten + Freitext)

Validierung: OK-Button bleibt deaktiviert, solange ein Feld leer ist.
Der Save-Pfad wird im Anschluss über einen `QFileDialog` ausgewählt – die
Dialog-Instanz hält ihn nach `exec()` in `_db_path`.
"""

from __future__ import annotations

import getpass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import DB_FILE_SUFFIX, ENGAGEMENTS_DIR, sanitize_for_path
from sampling_tool.core.models import Engagement

AUDIT_TYPES: tuple[str, ...] = (
    "ISAE 3402 Typ 2",
    "IDW PS 951",
    "Sonstige",
)


class NewEngagementDialog(QDialog):
    """Dialog für die Erstanlage eines Engagements."""

    def __init__(
        self,
        parent: QWidget | None = None,
        default_auditor_name: str | None = None,
        engagements_dir: Path | None = None,
        initial_engagement: Engagement | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neues Engagement anlegen")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._db_path: Path | None = None
        self._engagements_dir = engagements_dir if engagements_dir is not None else ENGAGEMENTS_DIR

        # ---- Felder ----
        # `initial_engagement` schlägt Auditor/Position/Mandant aus
        # `default_auditor_name`, wenn beide gesetzt sind – Use-Case ist das
        # erneute Öffnen nach Duplikat-Konflikt, da soll der zuletzt
        # eingegebene Auditor wieder erscheinen, nicht der OS-Default.
        initial_auditor = (
            initial_engagement.auditor_name
            if initial_engagement is not None
            else (default_auditor_name or _default_user_name())
        )
        self._auditor_name = QLineEdit(initial_auditor)
        self._auditor_position = QLineEdit(
            initial_engagement.auditor_position if initial_engagement is not None else ""
        )
        self._client_name = QLineEdit(
            initial_engagement.client_name if initial_engagement is not None else ""
        )

        self._audit_type_combo = QComboBox()
        self._audit_type_combo.addItems(AUDIT_TYPES)
        self._audit_type_combo.setEditable(False)

        self._audit_type_other = QLineEdit()
        self._audit_type_other.setPlaceholderText('Freitext für „Sonstige"…')
        self._audit_type_other.setVisible(False)

        if initial_engagement is not None and initial_engagement.audit_type:
            if initial_engagement.audit_type in AUDIT_TYPES:
                self._audit_type_combo.setCurrentText(initial_engagement.audit_type)
            else:
                self._audit_type_combo.setCurrentText("Sonstige")
                self._audit_type_other.setText(initial_engagement.audit_type)

        # ---- Layout ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        intro = QLabel(
            "Bitte alle Felder ausfüllen. Pro Engagement wird eine eigene "
            "SQLite-Datei angelegt – im nächsten Schritt wählst du den "
            "Speicherort."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #7F7F7F;")
        outer.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow("Auditor-Name *", self._auditor_name)
        form.addRow("Position *", self._auditor_position)
        form.addRow("Mandant *", self._client_name)
        form.addRow("Prüfungstyp *", self._audit_type_combo)
        form.addRow("", self._audit_type_other)
        outer.addLayout(form)

        # ---- Buttons ----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("Speicherort wählen…")
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)

        # ---- Reaktivitäten ----
        for field in (self._auditor_name, self._auditor_position, self._client_name):
            field.textChanged.connect(self._update_ok_enabled)
        self._audit_type_other.textChanged.connect(self._update_ok_enabled)
        self._audit_type_combo.currentTextChanged.connect(self._on_audit_type_changed)

        self._on_audit_type_changed(self._audit_type_combo.currentText())
        self._update_ok_enabled()

    # ---- Public API -----------------------------------------------------

    def get_engagement(self) -> Engagement:
        """Erzeugt das `Engagement`-Domain-Objekt – nur nach `accept()` aufrufen."""
        return Engagement(
            auditor_name=self._auditor_name.text().strip(),
            auditor_position=self._auditor_position.text().strip(),
            client_name=self._client_name.text().strip(),
            audit_type=self._selected_audit_type(),
        )

    def get_db_path(self) -> Path:
        """Pfad zur neu anzulegenden SQLite-Datei (nur nach `accept()` valide)."""
        if self._db_path is None:
            raise RuntimeError("DB-Pfad ist erst nach erfolgreichem `accept()` verfügbar.")
        return self._db_path

    # ---- intern --------------------------------------------------------

    def _selected_audit_type(self) -> str:
        if self._audit_type_combo.currentText() == "Sonstige":
            return self._audit_type_other.text().strip()
        return self._audit_type_combo.currentText()

    def _is_valid(self) -> bool:
        if not self._auditor_name.text().strip():
            return False
        if not self._auditor_position.text().strip():
            return False
        if not self._client_name.text().strip():
            return False
        return bool(self._selected_audit_type())

    def _update_ok_enabled(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(self._is_valid())

    def _on_audit_type_changed(self, text: str) -> None:
        is_other = text == "Sonstige"
        self._audit_type_other.setVisible(is_other)
        if not is_other:
            self._audit_type_other.clear()
        self._update_ok_enabled()

    def _on_accept(self) -> None:
        if not self._is_valid():
            return

        sanitized = sanitize_for_path(self._client_name.text().strip())
        default_dir = self._engagements_dir / sanitized
        default_dir.mkdir(parents=True, exist_ok=True)
        default_target = default_dir / f"{sanitized}{DB_FILE_SUFFIX}"
        path_str, _filter = QFileDialog.getSaveFileName(
            self,
            "Engagement speichern",
            str(default_target),
            f"SQLite-Engagement (*{DB_FILE_SUFFIX})",
        )
        if not path_str:
            return

        target = Path(path_str)
        if target.suffix.lower() != DB_FILE_SUFFIX:
            target = target.with_suffix(DB_FILE_SUFFIX)

        # Kollision mit bestehendem Engagement wird im Controller via
        # `DuplicateEngagementDialog` behandelt – siehe `MainController.
        # handle_new_engagement`. Hier nur den Pfad bestätigen.
        self._db_path = target
        self.accept()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802
        # Enter darf das Formular nicht abschicken, solange ein Feld leer ist.
        if (
            event is not None
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not self._is_valid()
        ):
            event.accept()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _default_user_name() -> str:
    """OS-Username (Fallback für Auditor-Name)."""
    try:
        return getpass.getuser()
    except OSError:  # pragma: no cover – sehr defensiv
        return ""
