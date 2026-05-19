"""Zentrale Formatierungs-Helfer für Anzeige-Werte (Sprint 18 / Q-005).

Bevor dieses Modul existierte, war die Audit-Trail-Timestamp-Formatierung
in fünf Stellen dupliziert (audit_trail_view, dashboard_view,
pdf_report, multi_report_exporter, html_report). Vier Implementierungen
normalisierten die Zeitzone (UTC → lokal) korrekt, der PDF-Pfad NICHT –
Resultat: derselbe Event zeigte in UI und PDF unterschiedliche Uhrzeiten
(Q-005, Pass 2 SEV-2).

Eintrittspunkt für ALLE Audit-Anzeige-Pfade: `format_event_timestamp`.
DB-Speicherung bleibt unverändert (UTC-aware ISO-8601, siehe
`persistence/database.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime

# 19-Zeichen-Format: konsistent zwischen UI, PDF, Excel-Report, HTML-Report.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def ensure_utc(ts: datetime) -> datetime:
    """Stellt sicher, dass ``ts`` UTC-aware ist.

    Naive datetimes (alte DB-Daten ohne TZ) werden als UTC interpretiert –
    Konvention für DB-gespeicherte Werte (`persistence/database.py`).
    Aware datetimes werden NICHT umgerechnet, nur durchgereicht.
    """
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def format_event_timestamp(ts: datetime) -> str:
    """Einheitliche Timestamp-Formatierung für alle Audit-Trail-Anzeigen.

    Normalisiert auf lokale Zeitzone, formatiert als
    ``YYYY-MM-DD HH:MM:SS``. Naive datetimes werden via `ensure_utc` als
    UTC interpretiert. Der Lokal-TZ-Wechsel passiert dann via
    `datetime.astimezone()` – konsistent mit Python-System-Locale.
    """
    return ensure_utc(ts).astimezone().strftime(_TIMESTAMP_FORMAT)


def format_optional_timestamp(ts: datetime | None) -> str:
    """Wie `format_event_timestamp`, liefert aber für ``None`` einen Em-Dash.

    Wird von der UI verwendet, wenn Events ohne Timestamp angezeigt werden
    sollen (sehr seltener Edge-Case – Trigger setzt CURRENT_TIMESTAMP per
    Default).
    """
    if ts is None:
        return "—"
    return format_event_timestamp(ts)
