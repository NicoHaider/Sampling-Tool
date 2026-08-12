"""HTML-Report-Generator für E-Mail-Versand.

`HtmlReportGenerator` rendert ein einzelnes selbstständiges HTML-File via
Jinja2. CSS ist inline, Charts werden als Base64-PNG eingebettet – damit
funktioniert der Report ohne externe Assets und kann per E-Mail oder
File-Share verteilt werden.

Template-Default: `resources/templates/audit_report.html` (Top-Level-
Resource, im Bundle unter `sys._MEIPASS/resources/templates/`). Custom
Templates können über `template_path` injiziert werden.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from jinja2 import (
    BaseLoader,
    Environment,
    FileSystemLoader,
    TemplateNotFound,
)

from sampling_tool import __version__
from sampling_tool.core.formatting import format_audit_details, format_optional_timestamp
from sampling_tool.core.models import AuditEvent, Dataset, Engagement, SampleResult
from sampling_tool.core.provenance import SamplingProvenance
from sampling_tool.io._atomic import atomic_output
from sampling_tool.io.charts import (
    render_bar_chart_bytes,
    render_line_chart_bytes,
)
from sampling_tool.resources import shared_resource

_DEFAULT_TEMPLATE_DIR: Final[Path] = shared_resource("templates")
_DEFAULT_TEMPLATE_NAME: Final[str] = "audit_report.html"
_HISTORY_DAYS: Final[int] = 30


def _utc_now() -> datetime:
    """Default-Uhr des rollenden 30-Tage-Fensters.

    Steht bewusst hier oben und nicht im Hilfen-Block am Dateiende: Python
    wertet Default-Argumente beim Definieren der Funktion aus, und
    `HtmlReportGenerator.__init__` nutzt diese Funktion als Default für
    `now_provider` (gleiche Reihenfolge wie in `ui/widgets/audit_trail_view.py`).
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _SampleView:
    """View-Modell für ein Sample im Template – mit formatierten Strings."""

    id: int | None
    config: Any
    actual_size: int
    population_size: int
    percent_str: str
    drawn_at_str: str
    size_requested: int
    filter_operator_symbol: str
    parent_sample_id: int | None
    algorithm_version: str
    dataset_id: int | None


@dataclass(frozen=True, slots=True)
class _EventView:
    """View-Modell für einen AuditEvent im Template."""

    timestamp_str: str
    event_type: str
    user_name: str
    sample_id: int | None
    sample_size: int | None
    percent_str: str
    seed: int | None
    filename: str
    corrects_event_id: int | None
    details_str: str


class HtmlReportGenerator:
    """Rendert einen Engagement-HTML-Report (selbstständige Datei).

    Sprint 74 / Befund D: Der Report rechnet gegen eine injizierbare Uhr
    (`now_provider`, Default `_utc_now`) statt direkt gegen `datetime.now`.
    Vorher konnte kein Test das rollende 30-Tage-Fenster der Sampling-Historie
    dauerhaft treffen – ein Test mit gepinntem `drawn_at` lief mit
    fortschreitendem Kalender aus dem Fenster heraus und prüfte danach
    stillschweigend nichts mehr. Die 30-Tage-Semantik selbst ist unverändert.
    """

    def __init__(
        self,
        template_path: Path | None = None,
        *,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._now_provider = now_provider
        loader: BaseLoader
        if template_path is None:
            loader = FileSystemLoader(str(_DEFAULT_TEMPLATE_DIR))
            self._template_name = _DEFAULT_TEMPLATE_NAME
        else:
            if not template_path.exists():
                raise FileNotFoundError(f"Template nicht gefunden: {template_path}")
            loader = FileSystemLoader(str(template_path.parent))
            self._template_name = template_path.name
        self._env = Environment(
            loader=loader,
            autoescape=True,
            keep_trailing_newline=True,
        )

    def render(
        self,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
        output_path: Path,
        include_charts: bool = True,
        include_audit_trail: bool = True,
        include_samples_table: bool = True,
        dataset_ids_by_sample: dict[int, int] | None = None,
    ) -> Path:
        """Erzeugt den Report und schreibt ihn als .html nach `output_path`.

        Die `include_*`-Flags schalten optionale Blöcke ab. Standard ist „alles
        an" – damit bleiben bestehende Aufrufer unverändert. `dataset_ids_by_
        sample` (Sprint 43 / A-001) bildet `sample.id -> dataset.id` ab.
        """
        target = (
            output_path
            if output_path.suffix.lower() == ".html"
            else output_path.with_suffix(".html")
        )

        try:
            template = self._env.get_template(self._template_name)
        except TemplateNotFound as exc:
            raise FileNotFoundError(f"Template '{self._template_name}' nicht gefunden.") from exc

        # Eine Uhr pro Render-Vorgang: dasselbe „jetzt" begrenzt das
        # Historien-Fenster und stempelt die Fußzeile.
        now = self._now_provider()
        method_chart = _method_chart_base64(samples) if include_charts else None
        history_chart = _history_chart_base64(samples, now) if include_charts else None
        resolved_dataset_ids = dataset_ids_by_sample or {}

        ctx = {
            "title": f"Audit-Bericht – {engagement.client_name}",
            "engagement": engagement,
            "datasets": datasets,
            "samples": [_to_sample_view(s, resolved_dataset_ids) for s in samples],
            "events": [_to_event_view(e) for e in audit_events],
            "stats": {
                "datasets": len(datasets),
                "samples": len(samples),
                "events": len(audit_events),
                "last_activity": _last_activity(audit_events),
            },
            "method_chart_b64": method_chart,
            "history_chart_b64": history_chart,
            "include_charts": include_charts,
            "include_audit_trail": include_audit_trail,
            "include_samples_table": include_samples_table,
            # Aus DEMSELBEN Zeitpunkt wie das Historien-Fenster, in lokale
            # Zeit gedreht. Ergebnis-String identisch zum vorherigen
            # `datetime.now().strftime(...)` – nur eben nicht mehr eine
            # zweite, unabhängige Ablesung.
            "generated_at": now.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        }
        rendered = template.render(**ctx)
        with atomic_output(target) as tmp:
            tmp.write_text(rendered, encoding="utf-8")
        return target


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _to_sample_view(sample: SampleResult, dataset_ids_by_sample: dict[int, int]) -> _SampleView:
    percent = sample.actual_size / sample.population_size * 100.0 if sample.population_size else 0.0
    dataset_id = dataset_ids_by_sample.get(sample.id) if sample.id is not None else None
    provenance = SamplingProvenance.from_sample_result(
        sample, dataset_id=dataset_id, app_version=__version__
    )
    return _SampleView(
        id=sample.id,
        config=sample.config,
        actual_size=sample.actual_size,
        population_size=sample.population_size,
        percent_str=f"{percent:.2f} %",
        drawn_at_str=format_optional_timestamp(sample.drawn_at),
        size_requested=provenance.size_requested,
        filter_operator_symbol=provenance.filter_operator_symbol,
        parent_sample_id=provenance.parent_sample_id,
        algorithm_version=provenance.algorithm_version,
        dataset_id=provenance.dataset_id,
    )


def _to_event_view(event: AuditEvent) -> _EventView:
    percent_str = f"{event.sample_percent:.2f} %" if event.sample_percent is not None else "—"
    filename = Path(event.export_file or event.import_file or "").name or "—"
    return _EventView(
        timestamp_str=format_optional_timestamp(event.timestamp),
        event_type=event.event_type,
        user_name=event.user_name,
        sample_id=event.sample_id,
        sample_size=event.sample_size,
        percent_str=percent_str,
        seed=event.seed,
        filename=filename,
        corrects_event_id=event.corrects_event_id,
        details_str=format_audit_details(event.details),
    )


def _last_activity(events: list[AuditEvent]) -> str:
    if not events:
        return "—"
    latest = max(events, key=lambda e: e.timestamp)
    return format_optional_timestamp(latest.timestamp)


def _method_chart_base64(samples: list[SampleResult]) -> str | None:
    if not samples:
        return None
    counts: Counter[str] = Counter(s.config.method.value for s in samples)
    labels = list(counts.keys())
    values = [float(counts[k]) for k in labels]
    raw = render_bar_chart_bytes(labels, values, title="", width=560, height=240)
    return base64.b64encode(raw).decode("ascii")


def _history_chart_base64(samples: Iterable[SampleResult], now: datetime) -> str | None:
    """Sampling-Historie der letzten `_HISTORY_DAYS` Tage.

    `now` kommt von außen (Sprint 74 / Befund D) – das Fenster ist damit in
    Tests deterministisch treffbar. Semantik unverändert: halboffenes
    Fenster `[now - 30 Tage, now]`, gerechnet auf UTC-Kalendertagen.
    """
    samples_list = list(samples)
    if not samples_list:
        return None
    today = now.astimezone(UTC).date() if now.tzinfo is not None else now.date()
    bins: defaultdict[str, int] = defaultdict(int)
    for sample in samples_list:
        when = sample.drawn_at
        when_utc = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
        d = when_utc.date()
        if (today - d).days < _HISTORY_DAYS:
            bins[d.isoformat()] += 1
    labels: list[str] = []
    values: list[float] = []
    for offset in range(_HISTORY_DAYS - 1, -1, -1):
        date_key = (today - timedelta(days=offset)).isoformat()
        labels.append(date_key[5:])
        values.append(float(bins.get(date_key, 0)))
    raw = render_line_chart_bytes(labels, values, title="", width=620, height=200)
    return base64.b64encode(raw).decode("ascii")
