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

`format_cell_value` ist die SSOT für die Anzeige von Datensatz-Zellwerten
(Datentabelle, Import-Vorschau, Sidebar-ID-Werte) – Sprint 82 / Befund A.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any, Final

from sampling_tool.config import (
    AUDIT_DETAIL_LABELS,
    FILTER_OPERATOR_LABELS,
    METHOD_LABELS,
    PARENT_RELATION_LABELS,
    RESTORED_STATE_LABELS,
    STRATIFY_MODE_LABELS,
)
from sampling_tool.core.filter_values import decode_filter_value
from sampling_tool.core.models import FilterCondition, FilterOperator, SamplingMethod

# 19-Zeichen-Format: konsistent zwischen UI, PDF, Excel-Report, HTML-Report.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Excel zeigt Zahlen mit höchstens 15 signifikanten Stellen (Sprint 85 / C).
_MAX_SIGNIFICANT_DIGITS: Final = 15
# Genug Stellen für jede Quantisierung eines float (max. 17 Stellen im repr);
# unabhängig vom globalen Decimal-Kontext des Prozesses.
_ROUNDING_CONTEXT: Final = Context(prec=40)

# Sprint 92: Verbindung mehrerer Filterbedingungen in jeder Anzeige.
FILTER_JOINER: Final = " UND "

# Detail-Schlüssel der Einzelfilter-Events vor Sprint 92; ab Sprint 92 nur noch
# bei genau einem Filter zusätzlich zu `filters` geschrieben.
_LEGACY_FILTER_KEYS: Final = ("filter_field", "filter_value", "filter_operator")

# Sprint 93: Operatoren, deren Wert aus dem Schwellenwert-Feld des Dialogs stammt.
_ORDERING_OPERATORS: Final = frozenset(
    op.value
    for op in (FilterOperator.GT, FilterOperator.GTE, FilterOperator.LT, FilterOperator.LTE)
)

# Detail-Schlüssel, deren WERT ein Enum-Rohwert ist und übersetzt angezeigt wird.
_DETAIL_VALUE_LABELS: Final[dict[str, Mapping[Any, str]]] = {
    "method": METHOD_LABELS,
    "stratify_mode": STRATIFY_MODE_LABELS,
    "filter_operator": FILTER_OPERATOR_LABELS,
    "parent_relation": PARENT_RELATION_LABELS,
    "restored": RESTORED_STATE_LABELS,
}


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


def format_header_row(header_row: int | None) -> str:
    """Anzeige der Import-Kopfzeile (Sprint 83): 1-basiert wie im Import-Dialog.

    ``0`` heißt „keine Kopfzeile, Spaltennamen generiert"; ``None`` heißt
    „nicht erfasst" (Import vor Migration 006) und bleibt ein Em-Dash.
    """
    if header_row is None:
        return "—"
    if header_row == 0:
        return "keine (Spaltennamen generiert)"
    return f"Zeile {header_row}"


def format_audit_details(details: dict[str, Any]) -> str:
    """Kompakte Ein-Zeilen-Darstellung eines `AuditEvent.details`-Dicts.

    Einheitlicher Renderer für alle AuditTrail-„Details"-Anzeigen (Projekt-
    XLSX-AuditTrail-Spalte, PDF-/HTML-AuditTrail additiv) – Sprint 43 / A-001.

    Sprint 83 / D: Schlüssel erscheinen mit deutschem Namen
    (`AUDIT_DETAIL_LABELS`), Enum-Rohwerte übersetzt, Listen als
    „a, b" statt Python-Darstellung, `None`-Einträge entfallen. Unbekannte
    Schlüssel und Werte erscheinen roh – nie verschluckt. Die Reihenfolge ist
    die des Dicts. Ohne anzeigbaren Eintrag (leeres Dict, Alt-Events vor
    Sprint 43, nur `None`-Werte) kommt `"—"`.
    """
    parts: list[str] = []
    filter_text = _details_filter_text(details)
    for key, value in details.items():
        if filter_text is not None and key in ("filters", *_LEGACY_FILTER_KEYS):
            # Sprint 92: ein Eintrag „Filter: A = „x“ UND B ≥ 1000" an der Stelle
            # des ersten Filter-Schlüssels statt Feld/Wert/Operator einzeln.
            if filter_text:
                parts.append(f"{AUDIT_DETAIL_LABELS['filters']}: {filter_text}")
                filter_text = ""
            continue
        if value is not None and not _irrelevant_detail(key, details):
            parts.append(f"{AUDIT_DETAIL_LABELS.get(key, key)}: {_format_detail_value(key, value)}")
    return " · ".join(parts) if parts else "—"


def format_filters(filters: Sequence[FilterCondition]) -> str:
    """Anzeige der Filter einer Ziehung: „Kostenstelle = „Vertrieb“ UND Betrag ≥ 1000".

    Die eine Formatierung für Metadaten, Berichte, AuditTrail-Details und die
    Vorlagenverwaltung (Sprint 92). Ohne Filter `"—"` – und nur dann (Sprint 93).
    """
    return _join_conditions((c.field, c.operator.value, c.value) for c in filters)


def detail_filter_conditions(details: Mapping[str, Any]) -> list[tuple[str, str, Any]]:
    """Filter eines Stichproben-Events als (Feld, Operator-Rohwert, Wert).

    Liest `filters` (ab Sprint 92); Bestandsevents tragen nur die Einzelschlüssel
    `filter_field`/`filter_value`/`filter_operator` und werden nie umgeschrieben
    (append-only) – dann daraus eine Ein-Element-Liste, ohne Filter-Feld leer.
    Werte in `filters` tragen ab Sprint 93 einen Typ-Tag für Datum/Zeit.
    """
    raw = details.get("filters")
    if isinstance(raw, list):
        return [
            (
                str(item.get("field")),
                str(item.get("operator", "eq")),
                decode_filter_value(item.get("value")),
            )
            for item in raw
            if isinstance(item, dict)
        ]
    field = details.get("filter_field")
    if field is None:
        return []
    return [(str(field), str(details.get("filter_operator", "eq")), details.get("filter_value"))]


def _details_filter_text(details: Mapping[str, Any]) -> str | None:
    """Filter-Text für `format_audit_details`; `None` = Schlüssel roh anzeigen.

    Roh bleibt ein Dict, das weder `filters` noch ein `filter_field` hat (z. B.
    nur ein Operator) – nie etwas verschlucken, was sich nicht zuordnen lässt.
    """
    if "filters" not in details and details.get("filter_field") is None:
        return None
    conditions = detail_filter_conditions(details)
    return _join_conditions(conditions) if conditions else ""


def _join_conditions(conditions: Iterable[tuple[str, str, Any]]) -> str:
    texts = [
        f"{field} {FILTER_OPERATOR_LABELS.get(operator, operator)} "
        f"{_format_filter_value(_legacy_temporal(operator, value))}"
        for field, operator, value in conditions
    ]
    return FILTER_JOINER.join(texts) if texts else "—"


def _legacy_temporal(operator: str, value: Any) -> Any:
    """ISO-Text bei `>`/`≥`/`<`/`≤` als `datetime` – Bestandsdaten vor Sprint 93.

    Bis Sprint 92 landete ein Datums-Filterwert ohne Typ-Tag als ISO-Text in
    Event und `samples`. Bei diesen Operatoren ist das eindeutig: das
    Schwellenwert-Feld des Dialogs macht aus jedem ISO-lesbaren Text ein
    `datetime`, ein gespeicherter ISO-Text war also immer ein Datum. Bei `=`/`≠`
    kann er auch eine Textzelle gewesen sein – dort bleibt er Text. Nur Anzeige.
    """
    if operator not in _ORDERING_OPERATORS or not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _format_filter_value(value: Any) -> str:
    """Filterwert mit am Text erkennbarem Typ (Sprint 93).

    Text in „…“ (Rand-Leerzeichen bleiben innen), Zahlen/Ja-Nein/Datum wie die
    Zelle, die sie treffen – ohne Tausenderpunkt, sonst wären der Text „1.000"
    und die Zahl 1000 gleich. Leerer Text, reine Leerzeichen und `None` haben je
    einen eigenen Hinweis; `—` bleibt „kein Filter" vorbehalten.
    """
    if value is None:
        return "(kein Wert)"
    if isinstance(value, str):
        if value == "":
            return "(leer)"
        if value.strip() == "":
            return "(nur Leerzeichen)"
        return f"„{value}“"
    return format_cell_value(value)


def format_int(value: int) -> str:
    """Tausenderpunkte für deutsche Locale (12345 → '12.345')."""
    return f"{value:,}".replace(",", ".")


def _irrelevant_detail(key: str, details: dict[str, Any]) -> bool:
    """Operator ohne Filter-Feld, Schichtungsmodus ohne „Geschichtet" (Sprint 85 / E1).

    Beide stehen in jeder Ziehung in der DB (der Dialog setzt Defaults), sagen
    aber nur etwas, wenn ihr Bezug gilt. Weggelassen wird nur, wenn der
    Bezugsschlüssel vorhanden ist – ein fremdes Dict bleibt unverändert.
    """
    if key == "population_basis":
        # Sprint 89 / B3: technische Markierung – ihre Aussage trägt die
        # Population-Anzeige (`provenance.format_event_details`).
        return True
    if key == "filter_operator":
        return "filter_field" in details and details["filter_field"] is None
    if key == "stratify_mode":
        return "method" in details and details["method"] != SamplingMethod.STRATIFIED.value
    return False


def _format_detail_value(key: str, value: Any) -> str:
    """Anzeige eines Detail-Werts: übersetzt, Listen verbunden, sonst skalar."""
    if key == "header_row" and isinstance(value, int) and not isinstance(value, bool):
        return format_header_row(value)
    labels = _DETAIL_VALUE_LABELS.get(key)
    if labels is not None and isinstance(value, str):
        return labels.get(value, value)
    if isinstance(value, list | tuple):
        return ", ".join(_format_scalar(item) for item in value) or "—"
    return _format_scalar(value)


def _format_scalar(value: Any) -> str:
    """`None` → "—", `bool` → "ja"/"nein", sonst `str(value)`."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    return str(value)


def format_cell_value(value: Any) -> str:
    """Anzeige-Text eines Datensatz-Zellwerts (Ja/Nein, ISO-Datum, Dezimalpunkt, kein Runden).

    Floats erscheinen verlustfrei und nie in Exponent-Schreibweise – das
    frühere `:g`-Format hat auf 6 signifikante Stellen gerundet
    (13134.97 → „13135", Sprint 82 / Befund A).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, datetime):
        # Excel-Importe ohne Uhrzeit kommen als datetime mit 00:00:00 rein –
        # dann sähe " ... 00:00:00" wie ein Bug aus. Nur Datum anzeigen.
        if value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float):
        return _format_float(value)
    return str(value)


def _format_float(value: float) -> str:
    """Festkomma mit höchstens 15 signifikanten Stellen wie Excel; `nan`/`inf` → `str`.

    Sprint 85 / C: Ausgangspunkt bleiben die `repr`-Ziffern (kürzeste
    verlustfreie Form); erst wenn die mehr als 15 Stellen hat, wird kaufmännisch
    auf 15 gerundet – so zeigt `0.1 + 0.2` „0.3" statt des binären Rests.
    Reine Anzeige: Exporte und DB behalten den vollen Wert.
    """
    if not math.isfinite(value):
        return str(value)
    # `float(...)`: Subklassen (z. B. numpy float64) haben ein eigenes repr, das
    # Decimal nicht parst. Format "f" hängt – anders als `normalize()` – nicht
    # vom Decimal-Kontext ab; Quantisieren bekommt einen eigenen Kontext.
    number = Decimal(repr(float(value)))
    if len(number.as_tuple().digits) > _MAX_SIGNIFICANT_DIGITS:
        exponent = number.adjusted() - (_MAX_SIGNIFICANT_DIGITS - 1)
        number = number.quantize(
            Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP, context=_ROUNDING_CONTEXT
        )
    text = format(number, "f")
    # Nur Nachkommastellen kürzen – ohne Punkt würde rstrip die Ziffern von
    # ganzzahligen Beträgen wie 1e16 zerstören.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
