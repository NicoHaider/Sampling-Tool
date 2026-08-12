"""Gemeinsame Basis-Komponente für alle Export-Dialoge.

`ExportTargetWidget` bündelt die rechte Spalte aller Export-Dialoge:
Dateiname, ID, Zielordner, Vorschau-Label. Damit haben Sample-Export,
AuditTrail-PDF, Excel-Report und HTML-Report ein einheitliches UI.

Der Widget feuert `changed`, sobald irgendetwas sich ändert – Dialoge nutzen
das, um den OK-Button live zu (de-)aktivieren und ggf. weitere Vorschauen
zu aktualisieren.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import (
    EXPORT_FILENAME_PATTERN,
    export_date_token,
    local_export_now,
    sanitize_export_filename_token,
)

# Sprint 74 / §2.3: das Pattern lebt in `config.py`. Der Name hier bleibt als
# Default-Argument von `ExportTargetWidget` erhalten, ist aber kein zweites
# Literal mehr, sondern dieselbe Konstante.
DEFAULT_FILENAME_PATTERN: str = EXPORT_FILENAME_PATTERN

# Sprint 71 / Befund 1: Hinweistexte als Konstanten, damit Tests sie
# importieren statt die Literale zu wiederholen.
HINT_MISSING_NAME: str = "Dateiname fehlt."
HINT_MISSING_ID: str = "ID fehlt."
HINT_NO_DIR: str = "Kein Zielordner gewählt – bitte „Ordner wählen…“ klicken."

# Sprint 72: dieselbe Rolle eine Ebene höher – Gründe, die NICHT im
# `ExportTargetWidget` liegen, sondern in der dialogspezifischen Auswahl.
HINT_NO_EVENT_TYPES: str = "Keine Ereignistypen gewählt – bitte mindestens einen anhaken."
HINT_NO_SHEETS: str = "Keine Report-Blätter gewählt – bitte mindestens eines anhaken."
HINT_NO_COLUMNS: str = "Keine Spalten gewählt – bitte mindestens eine anhaken."
# Nicht erreichbarer Zustand (Sprint 72 / §3.2, empirisch gemessen): der
# AuditTrail-PDF-Dialog fällt bei leerer `event_types_available` auf
# `_DEFAULT_TYPES` zurück UND hakt alles an, d. h. ein Projekt ohne
# Audit-Ereignisse blockiert den OK-Button nicht. Die Konstante bleibt als
# benannter Zustand bestehen und ist per Nicht-Erreichbarkeits-Test in
# `tests/ui/test_export_audit_pdf_dialog.py::TestEmptyAuditTrail` festgenagelt.
HINT_NO_AUDIT_EVENTS: str = "Keine Audit-Ereignisse im Projekt – es gibt nichts zu exportieren."


def hint_missing_dir(path: Path) -> str:
    """Hinweis für einen gesetzten, aber nicht existierenden Zielordner."""
    return f"Zielordner existiert nicht: {path} – bitte „Ordner wählen…“ klicken."


def apply_validation(
    ok_button: QAbstractButton | None,
    target: ExportTargetWidget,
    extra_hint: str = "",
) -> str:
    """Setzt Hinweistext und OK-Enablement aus EINER Quelle.

    Reihenfolge: die Ziel-Validierung (Name/ID/Ordner) hat Vorrang, danach der
    dialogspezifische Grund. Rückgabe = der wirksame Hinweis („" = alles gültig).

    Sprint 72: der einzige Verdrahtungspunkt für alle vier Export-Dialoge.
    Vorher hing das OK-Enablement zusätzlich an einer Auswahl, die
    `validation_hint()` nicht sehen kann – abwählen machte den Button grau,
    ohne dass irgendwo stand warum. Damit gilt ab jetzt hart: **OK ist genau
    dann aktiv, wenn der Hinweistext leer ist.**
    """
    hint = target.validation_hint() or extra_hint
    target.show_hint(hint)
    if ok_button is not None:
        ok_button.setEnabled(not hint)
    return hint


class ExportTargetWidget(QWidget):
    """Wiederverwendbare rechte Spalte: Dateiname, ID, Zielordner, Vorschau.

    Sprint 74 / Befund B: Der Zeitpunkt für den `{date}`-Token wird GENAU
    EINMAL bei der Konstruktion gelesen und danach gemerkt. Vorher las
    `preview_filename()` die Wanduhr bei jedem Aufruf – schon zwischen zwei
    Tastendrücken konnte sich der angezeigte Dateiname ändern, und der Writer
    las noch eine dritte Uhr. Lief ein Export über einen Tageswechsel, hieß
    die Datei anders als die Vorschau. Der gemerkte Zeitpunkt geht über
    `now()` nach außen und wird bis in den Export-Task durchgereicht.
    """

    changed = pyqtSignal()

    def __init__(
        self,
        default_name: str = "",
        default_id: str = "",
        file_extension: str = "",
        filename_pattern: str = DEFAULT_FILENAME_PATTERN,
        type_token: str = "export",
        default_output_dir: Path | None = None,
        parent: QWidget | None = None,
        *,
        now_provider: Callable[[], datetime] = local_export_now,
    ) -> None:
        super().__init__(parent)
        self._file_extension = file_extension
        self._filename_pattern = filename_pattern
        self._type_token = type_token
        self._output_dir: Path | None = default_output_dir
        # Die EINE Uhr-Lesung dieses Export-Vorgangs.
        self._now_provider = now_provider
        self._now = now_provider()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_caption("Dateiname *"))
        self._name_field = QLineEdit(default_name)
        layout.addWidget(self._name_field)

        layout.addWidget(_caption("ID *"))
        self._id_field = QLineEdit(default_id)
        layout.addWidget(self._id_field)

        layout.addWidget(_caption("Zielordner *"))
        dir_row = QHBoxLayout()
        self._dir_label = QLabel(
            str(self._output_dir) if self._output_dir is not None else "(noch nicht gewählt)"
        )
        self._dir_label.setStyleSheet("color: #555555;")
        self._dir_label.setWordWrap(True)
        self._dir_button = QPushButton("Ordner wählen…")
        self._dir_button.setProperty("secondary", True)
        dir_row.addWidget(self._dir_label, stretch=1)
        dir_row.addWidget(self._dir_button)
        layout.addLayout(dir_row)

        layout.addSpacing(8)
        layout.addWidget(_caption("Vorschau Dateiname"))
        self._preview_label = QLabel("")
        # Sprint 74: benannt, damit Tests das ANGEZEIGTE Label gegen den
        # geschriebenen Pfad prüfen können statt gegen `preview_filename()`
        # (das wäre eine Tautologie, keine Vorschau-Prüfung).
        self._preview_label.setObjectName("exportTargetPreview")
        self._preview_label.setStyleSheet("color: #7F7F7F; font-family: monospace;")
        self._preview_label.setWordWrap(True)
        layout.addWidget(self._preview_label)

        # Sprint 71 / Befund 1: sagt, WARUM der OK-Button grau ist. Inline
        # gestylt wie die Geschwister-Labels – bewusst keine QSS-Regel, damit
        # die Skalierungs-Gates (`test_scaling.py`) unberührt bleiben.
        self._hint_label = QLabel("")
        self._hint_label.setObjectName("exportTargetHint")
        self._hint_label.setStyleSheet("color: #C62828; background: transparent;")
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        layout.addWidget(self._hint_label)
        layout.addStretch(1)

        # ---- Signals ----
        self._name_field.textChanged.connect(self._on_field_changed)
        self._id_field.textChanged.connect(self._on_field_changed)
        self._dir_button.clicked.connect(self._choose_dir)

        self.update_preview()
        self._update_hint()

    # ---- Public API ----------------------------------------------------

    def get_name(self) -> str:
        """Liefert den getrimmten Dateinamen."""
        return self._name_field.text().strip()

    def get_id(self) -> str:
        """Liefert die getrimmte ID."""
        return self._id_field.text().strip()

    def get_output_dir(self) -> Path | None:
        """Liefert den gewählten Zielordner (oder `None`)."""
        return self._output_dir

    def get_path(self) -> Path | None:
        """Liefert den vollständigen Ziel-Pfad (Ordner + finaler Dateiname)."""
        if self._output_dir is None:
            return None
        return self._output_dir / self.preview_filename()

    def now(self) -> datetime:
        """Der EINE Zeitpunkt dieses Export-Vorgangs (bei Konstruktion gelesen).

        Aufrufer reichen ihn an den Writer weiter, damit die geschriebene
        Datei per Konstruktion so heißt wie die Vorschau (Sprint 74 / §2.2).
        """
        return self._now

    def now_provider(self) -> Callable[[], datetime]:
        """Die injizierte Uhr – für Dialoge, die denselben Zeitpunkt brauchen."""
        return self._now_provider

    def date_token(self) -> str:
        """`{date}`-Token dieses Export-Vorgangs."""
        return export_date_token(self._now)

    def preview_filename(self) -> str:
        """Aktueller Dateiname laut Pattern + Extension.

        Liest die Uhr NICHT – der Zeitpunkt steht seit der Konstruktion fest
        (Sprint 74). Zwei Aufrufe liefern denselben Namen, auch über
        Mitternacht hinweg.
        """
        name = sanitize_export_filename_token(self.get_name() or "export")
        sid = sanitize_export_filename_token(self.get_id() or "0")
        body = self._filename_pattern.format(
            name=name,
            id=sid,
            type=self._type_token,
            date=self.date_token(),
        )
        return f"{body}{self._file_extension}"

    def validation_hint(self) -> str:
        """Konkreter Grund, warum der Export (noch) nicht startbar ist.

        Leerer String = gültig. Single Source of Truth – `is_valid()` leitet
        sich davon ab, damit es keinen zweiten Prüfpfad gibt.
        """
        if not self.get_name():
            return HINT_MISSING_NAME
        if not self.get_id():
            return HINT_MISSING_ID
        if self._output_dir is None:
            return HINT_NO_DIR
        if not self._output_dir.is_dir():
            return hint_missing_dir(self._output_dir)
        return ""

    def is_valid(self) -> bool:
        """`True`, wenn Name, ID und ein existierender Zielordner gesetzt sind."""
        return not self.validation_hint()

    def update_preview(self) -> None:
        """Aktualisiert das Vorschau-Label – wird intern nach Änderungen aufgerufen."""
        self._preview_label.setText(self.preview_filename())

    def show_hint(self, text: str) -> None:
        """Zeigt `text` im Hinweis-Label (leer = Label ausblenden).

        Sprint 72: der Schreibzugang für `apply_validation`, damit der Dialog
        auch seinen eigenen Auswahl-Grund in dasselbe Label schreiben kann –
        bewusst ohne Callback vom Widget zurück in den Dialog.
        """
        self._hint_label.setText(text)
        self._hint_label.setVisible(bool(text))

    def set_output_dir(self, path: Path) -> None:
        """Setzt den Zielordner programmatisch (z. B. für Tests)."""
        self._output_dir = path
        self._dir_label.setText(str(path))
        self.update_preview()
        self._update_hint()
        self.changed.emit()

    # ---- Slots ---------------------------------------------------------

    def _update_hint(self) -> None:
        self.show_hint(self.validation_hint())

    def _on_field_changed(self) -> None:
        self.update_preview()
        self._update_hint()
        self.changed.emit()

    def _choose_dir(self) -> None:
        start = str(self._output_dir) if self._output_dir is not None else ""
        chosen = QFileDialog.getExistingDirectory(self, "Zielordner wählen", start)
        if chosen:
            self.set_output_dir(Path(chosen))


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #555555; font-weight: 600;")
    return label
