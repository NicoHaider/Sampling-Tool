"""HTML-Report-Generator für E-Mail-Versand.

`HtmlReportGenerator` rendert ein einzelnes selbstständiges HTML-File via
Jinja2. CSS ist inline, Charts werden als Base64-PNG eingebettet – damit
funktioniert der Report ohne externe Assets und kann per E-Mail oder
File-Share verteilt werden.

Template-Default: `<package>/resources/templates/audit_report.html`. Custom
Templates können über `template_path` injiziert werden.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from jinja2 import (
    BaseLoader,
    Environment,
    FileSystemLoader,
    TemplateNotFound,
    select_autoescape,
)

from sampling_tool.core.models import AuditEvent, Dataset, Engagement, SampleResult
from sampling_tool.ui.widgets.chart_renderer import (
    render_bar_chart_bytes,
    render_line_chart_bytes,
)

_DEFAULT_TEMPLATE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "resources" / "templates"
_DEFAULT_TEMPLATE_NAME: Final[str] = "audit_report.html"
_HISTORY_DAYS: Final[int] = 30


@dataclass(frozen=True, slots=True)
class _SampleView:
    """View-Modell für ein Sample im Template – mit formatierten Strings."""

    id: int | None
    config: Any
    actual_size: int
    population_size: int
    percent_str: str
    drawn_at_str: str


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


class HtmlReportGenerator:
    """Rendert einen Engagement-HTML-Report (selbstständige Datei)."""

    def __init__(self, template_path: Path | None = None) -> None:
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
            autoescape=select_autoescape(["html"]),
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
    ) -> Path:
        """Erzeugt den Report und schreibt ihn als .html nach `output_path`.

        Die `include_*`-Flags schalten optionale Blöcke ab. Standard ist „alles
        an" – damit bleiben bestehende Aufrufer unverändert.
        """
        target = (
            output_path
            if output_path.suffix.lower() == ".html"
            else output_path.with_suffix(".html")
        )
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            template = self._env.get_template(self._template_name)
        except TemplateNotFound as exc:
            raise FileNotFoundError(f"Template '{self._template_name}' nicht gefunden.") from exc

        method_chart = _method_chart_base64(samples) if include_charts else None
        history_chart = _history_chart_base64(samples) if include_charts else None

        ctx = {
            "title": f"Audit-Bericht – {engagement.client_name}",
            "engagement": engagement,
            "datasets": datasets,
            "samples": [_to_sample_view(s) for s in samples],
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
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        target.write_text(template.render(**ctx), encoding="utf-8")
        return target


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _to_sample_view(sample: SampleResult) -> _SampleView:
    percent = sample.actual_size / sample.population_size * 100.0 if sample.population_size else 0.0
    return _SampleView(
        id=sample.id,
        config=sample.config,
        actual_size=sample.actual_size,
        population_size=sample.population_size,
        percent_str=f"{percent:.2f} %",
        drawn_at_str=_format_dt(sample.drawn_at),
    )


def _to_event_view(event: AuditEvent) -> _EventView:
    percent_str = f"{event.sample_percent:.2f} %" if event.sample_percent is not None else "—"
    filename = Path(event.export_file or event.import_file or "").name or "—"
    return _EventView(
        timestamp_str=_format_dt(event.timestamp),
        event_type=event.event_type,
        user_name=event.user_name,
        sample_id=event.sample_id,
        sample_size=event.sample_size,
        percent_str=percent_str,
        seed=event.seed,
        filename=filename,
        corrects_event_id=event.corrects_event_id,
    )


def _last_activity(events: list[AuditEvent]) -> str:
    if not events:
        return "—"
    latest = max(events, key=lambda e: e.timestamp)
    return _format_dt(latest.timestamp)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    ts = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _method_chart_base64(samples: list[SampleResult]) -> str | None:
    if not samples:
        return None
    counts: Counter[str] = Counter(s.config.method.value for s in samples)
    labels = list(counts.keys())
    values = [float(counts[k]) for k in labels]
    raw = render_bar_chart_bytes(labels, values, title="", width=560, height=240)
    return base64.b64encode(raw).decode("ascii")


def _history_chart_base64(samples: Iterable[SampleResult]) -> str | None:
    samples_list = list(samples)
    if not samples_list:
        return None
    today = datetime.now(UTC).date()
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
