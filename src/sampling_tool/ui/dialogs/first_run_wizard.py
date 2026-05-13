"""Wizard für die Erst-Einrichtung beim allerersten App-Start.

Vier Pages: Begrüßung → Ordner-Auswahl → Auditor-Name → Zusammenfassung.
Bei Cancel/Close werden Defaults beibehalten – das `first_run_completed`-
Flag wird in jedem Fall vom Caller (`__main__`) gesetzt, damit der
Wizard nicht erneut auftaucht.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from sampling_tool import config


@dataclass(frozen=True, slots=True)
class FirstRunResult:
    """Ergebnis-Tuple aus dem Wizard – wird vom Caller in AppSettings gemerged."""

    engagements_dir: str
    default_auditor_name: str


class FirstRunWizard(QWizard):
    """Vierseitiger Erst-Einrichtungs-Wizard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Erst-Einrichtung")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setMinimumSize(560, 380)

        self._page_welcome = _WelcomePage()
        self._page_folder = _FolderPage()
        self._page_auditor = _AuditorPage()
        self._page_summary = _SummaryPage()

        self.addPage(self._page_welcome)
        self.addPage(self._page_folder)
        self.addPage(self._page_auditor)
        self.addPage(self._page_summary)

        self.setButtonText(QWizard.WizardButton.NextButton, "Weiter")
        self.setButtonText(QWizard.WizardButton.BackButton, "Zurück")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Fertig")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Abbrechen")

    def result_data(self) -> FirstRunResult:
        return FirstRunResult(
            engagements_dir=self._page_folder.chosen_path(),
            default_auditor_name=self._page_auditor.auditor_name(),
        )


class _WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Willkommen")
        self.setSubTitle(
            "Wir richten kurz deine Standard-Einstellungen ein – dauert etwa 30 Sekunden."
        )
        layout = QVBoxLayout(self)
        label = QLabel(
            "Dieses Tool zieht reproduzierbare Stichproben für Audit- und "
            "Compliance-Engagements. Auf den nächsten Seiten wählst du:\n\n"
            "  • Den Standard-Ordner für deine Engagement-Dateien\n"
            "  • Optional deinen Namen (wird in neuen Engagements vorbelegt)\n\n"
            'Alle Einstellungen lassen sich später unter „Einstellungen" '
            "jederzeit ändern."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)


class _FolderPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Standard-Ordner")
        self.setSubTitle("Hier speichert das Tool deine Engagement-Dateien (SQLite-DBs).")
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self._line_edit = QLineEdit(str(config.ENGAGEMENTS_DIR))
        self._browse_btn = QPushButton("Durchsuchen…")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        row.addWidget(self._line_edit, 1)
        row.addWidget(self._browse_btn)

        hint = QLabel(
            "Wenn der Ordner nicht existiert, wird er beim Weiterklicken automatisch angelegt."
        )
        hint.setStyleSheet("color: #7F7F7F; font-size: 11px;")
        hint.setWordWrap(True)

        layout.addLayout(row)
        layout.addWidget(hint)
        layout.addStretch(1)

    def _on_browse_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Engagements-Ordner wählen", self._line_edit.text()
        )
        if chosen:
            self._line_edit.setText(chosen)

    def chosen_path(self) -> str:
        return str(Path(self._line_edit.text()).expanduser().resolve())

    def validatePage(self) -> bool:  # noqa: N802 – Qt-Override
        target = Path(self._line_edit.text()).expanduser().resolve()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Ordner konnte nicht angelegt werden",
                "Der gewählte Ordner konnte nicht erstellt werden:\n"
                f"{exc}\n\nBitte wähle einen anderen Pfad oder prüfe "
                "die Berechtigungen.",
            )
            return False
        self._line_edit.setText(str(target))
        return True


class _AuditorPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Auditor-Name (optional)")
        self.setSubTitle(
            "Dein Name wird in neuen Engagements als Auditor vorbelegt. Kann leer bleiben."
        )
        layout = QVBoxLayout(self)
        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText("z. B. Max Mustermann")
        layout.addWidget(self._line_edit)
        layout.addStretch(1)

    def auditor_name(self) -> str:
        return self._line_edit.text().strip()


class _SummaryPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Zusammenfassung")
        self.setSubTitle(
            "Wenn alles passt, klick auf Fertig. Du kannst alle "
            "Einstellungen später jederzeit ändern."
        )
        layout = QVBoxLayout(self)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._summary)
        layout.addStretch(1)

    def initializePage(self) -> None:  # noqa: N802 – Qt-Override
        wiz = self.wizard()
        assert isinstance(wiz, FirstRunWizard)
        folder = wiz._page_folder.chosen_path()
        auditor = wiz._page_auditor.auditor_name()
        auditor_display = auditor if auditor else "(nicht gesetzt)"
        self._summary.setText(
            f"<b>Engagements-Ordner:</b><br>{folder}<br><br>"
            f"<b>Auditor-Name:</b><br>{auditor_display}"
        )
