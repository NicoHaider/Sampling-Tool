"""QSettings-Store für die optionale ID-Spalte pro Dataset (Sprint 31).

Bewusste Architektur-Entscheidung: die gewählte ID-Spalte ist ein reines
pro-Dataset-Anzeige-Metadatum für die Sidebar-Stichprobenliste. Sie berührt
weder Reproduzierbarkeit noch den Audit-Trail (ISAE-3402) – eine Ziehung ist
von ihr vollkommen unabhängig. Deshalb lebt sie app-weit in `QSettings`
(analog `ui/preset_store.py`) und **nicht** in der Projekt-DB: kein
Schema-Change, keine Migration (Hard Constraint).

Der Key ist `dataset_id_columns/<db_stem>/<dataset_id>`. `dataset.id` ist die
stabile SQLite-Row-ID pro Projekt-DB; der `db_stem` (Dateiname der `.db` ohne
Endung) macht den Key projektweit eindeutig, sodass sich Datasets aus
verschiedenen Projekten nie überschneiden.
"""

from __future__ import annotations

from sampling_tool.ui import settings_store

_PREFIX = "dataset_id_columns"


def _key(db_stem: str, dataset_id: int) -> str:
    """Projektweit eindeutiger QSettings-Key für die ID-Spalte eines Datasets."""
    return f"{_PREFIX}/{db_stem}/{dataset_id}"


class DatasetIdColumnStore:
    """Liest/schreibt die pro Dataset gemerkte ID-Spalte über `QSettings`.

    Stateless (jede Methode öffnet einen frischen Handle über
    `settings_store.open_qsettings`, denselben Isolations-Punkt wie
    `AppSettings`/`PresetStore`).
    """

    def get(self, db_stem: str, dataset_id: int) -> str | None:
        """Liefert die gemerkte ID-Spalte oder ``None``, wenn keine gewählt ist."""
        raw = settings_store.open_qsettings().value(_key(db_stem, dataset_id))
        text = "" if raw is None else str(raw)
        return text or None

    def set(self, db_stem: str, dataset_id: int, column: str | None) -> None:
        """Setzt (oder entfernt bei ``None``/leer) die ID-Spalte eines Datasets."""
        qs = settings_store.open_qsettings()
        key = _key(db_stem, dataset_id)
        if column:
            qs.setValue(key, column)
        else:
            qs.remove(key)
        qs.sync()
