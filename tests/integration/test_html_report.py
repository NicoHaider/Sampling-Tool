"""Tests für `HtmlReportGenerator` – Jinja-Render, Base64-Charts, Inhalt."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

import pytest

from sampling_tool.core.models import (
    AuditEvent,
    Engagement,
    FilterOperator,
    ParentRelation,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.provenance import SamplingProvenance
from sampling_tool.io import html_report
from sampling_tool.io.html_report import _HISTORY_DAYS, HtmlReportGenerator

pytestmark = pytest.mark.integration

# Sprint 74 / Befund D + §4.4: EIN Anker pro Testdatei, alle weiteren
# Zeitpunkte per timedelta abgeleitet – kein zweites Datums-Literal daneben.
#
# Vorher stand hier `datetime(2026, 5, 1, ...)` als festes Literal gegen ein
# rollendes 30-Tage-Fenster, das aus der WANDUHR gespeist wurde. Seit Ende
# Mai 2026 lag das Datum außerhalb des Fensters: der Histogramm-Zweig wurde
# nicht mehr betreten, der Test blieb grün und prüfte nichts mehr. Jetzt
# steht die Uhr des Generators still (`now_provider`), und die Sample-Daten
# hängen relativ am selben Anker – der Test kann nicht mehr aus dem Fenster
# herauswachsen.
FROZEN_NOW: Final = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

INSIDE_WINDOW: Final = FROZEN_NOW - timedelta(days=1)
LAST_DAY_INSIDE: Final = FROZEN_NOW - timedelta(days=_HISTORY_DAYS - 1)
FIRST_DAY_OUTSIDE: Final = FROZEN_NOW - timedelta(days=_HISTORY_DAYS)
FAR_OUTSIDE: Final = FROZEN_NOW - timedelta(days=_HISTORY_DAYS * 3)


def _generator(**kwargs: object) -> HtmlReportGenerator:
    """Generator mit auf `FROZEN_NOW` eingefrorener Uhr."""
    return HtmlReportGenerator(now_provider=lambda: FROZEN_NOW, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna Auditorin",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


@pytest.fixture
def samples() -> list[SampleResult]:
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42)
    return [
        SampleResult(
            config=cfg,
            selected_row_ids=(1, 2, 3, 4, 5),
            population_size=10,
            drawn_at=INSIDE_WINDOW,
            id=1,
        )
    ]


@pytest.fixture
def events() -> list[AuditEvent]:
    return [
        AuditEvent(
            event_type="sampling",
            engagement_id=1,
            user_name="anna",
            sample_id=1,
            sample_size=5,
            sample_percent=50.0,
            seed=42,
            timestamp=INSIDE_WINDOW,
            id=1,
        )
    ]


class TestHtmlReportGenerator:
    def test_render_creates_file(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        result = _generator().render(engagement, [], samples, events, out)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "<!doctype html>" in content.lower()

    def test_html_report_atomic_no_partial_on_write_error(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        """`html_report.py` schrieb bisher direkt via `target.write_text(...)`
        aufs Ziel – ein Fehler mittendrin (Disk voll, Berechtigung) hinterließ
        eine halbe HTML-Datei. Jetzt: atomar über `atomic_output`, kein
        Teil-Ergebnis am Ziel."""
        out = tmp_path / "report.html"
        with (
            patch("pathlib.Path.write_text", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            _generator().render(engagement, [], samples, events, out)
        assert not out.exists()
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == [], f"Kein .tmp-Rest erwartet, gefunden: {leftovers}"

    def test_html_contains_engagement_info(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        _generator().render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "ACME GmbH" in html
        assert "ISAE 3402" in html
        assert "Anna Auditorin" in html

    def test_html_embeds_base64_chart(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        _generator().render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        match = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
        assert match is not None, "Erwartet mind. eine Base64-eingebettete PNG-Grafik"
        # Base64 sollte sich dekodieren lassen und PNG-Header tragen.
        import base64

        decoded = base64.b64decode(match.group(1))
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_html_renders_without_samples(
        self,
        tmp_path: Path,
        engagement: Engagement,
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        _generator().render(engagement, [], [], events, out)
        html = out.read_text(encoding="utf-8")
        # Leerer Stichproben-Block muss noch enthalten sein, aber ohne Tabelle.
        assert "Noch keine Stichproben" in html

    def test_custom_template_path(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        custom = tmp_path / "tpl.html"
        custom.write_text(
            "<html><body><h1>{{ engagement.client_name }}</h1></body></html>",
            encoding="utf-8",
        )
        out = tmp_path / "out.html"
        _generator(template_path=custom).render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "<h1>ACME GmbH</h1>" in html

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            HtmlReportGenerator(template_path=tmp_path / "ghost.html")

    def test_include_charts_false_drops_base64_blocks(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "no_charts.html"
        _generator().render(engagement, [], samples, events, out, include_charts=False)
        html = out.read_text(encoding="utf-8")
        assert "data:image/png;base64," not in html
        assert "Sampling-Methoden" not in html
        assert "Sampling-Historie" not in html

    def test_include_audit_trail_false_skips_audit_section(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "no_audit.html"
        _generator().render(engagement, [], samples, events, out, include_audit_trail=False)
        html = out.read_text(encoding="utf-8")
        assert "AuditTrail" not in html

    def test_include_samples_table_false_skips_sample_section(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "no_samples.html"
        _generator().render(engagement, [], samples, events, out, include_samples_table=False)
        html = out.read_text(encoding="utf-8")
        # Die Stats-Karte „Stichproben" bleibt – aber die Samples-Tabelle und
        # ihre Header (<th>Methode</th>) verschwinden.
        assert "<h2>Stichproben</h2>" not in html
        assert "<th>Methode</th>" not in html

    def test_html_report_escapes_html_special_chars(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        malicious_engagement = replace(engagement, client_name='<b>&"Muster')
        out = tmp_path / "escaped.html"
        _generator().render(malicious_engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "<b>" not in html
        assert "&lt;b&gt;" in html
        assert "&amp;" in html
        assert "&#34;Muster" in html

    def test_samples_table_zeigt_volle_provenienz(
        self,
        tmp_path: Path,
        engagement: Engagement,
        events: list[AuditEvent],
    ) -> None:
        """A-001 Contract-Test: Filter, Parent, Algorithmus-Version,
        angeforderte Größe, Dataset-ID sind sichtbar."""
        cfg = SampleConfig(
            method=SamplingMethod.CLUSTER,
            size=5,
            seed=99,
            cluster_field="Land",
            filter_field="Betrag",
            filter_value=100,
            filter_operator=FilterOperator.GTE,
        )
        samples = [
            SampleResult(
                config=cfg,
                selected_row_ids=(1, 2, 3, 4, 5, 6, 7),
                population_size=10,
                parent_sample_id=17,
                created_by="anna",
                id=9,
                drawn_at=INSIDE_WINDOW,
            )
        ]
        out = tmp_path / "report.html"
        _generator().render(engagement, [], samples, events, out, dataset_ids_by_sample={9: 4})
        html = out.read_text(encoding="utf-8")
        assert "Betrag ≥ 100" in html
        assert "#17" in html
        assert "bdo-v1" in html
        assert "#4" in html

    def test_audit_trail_details_spalte_zeigt_details(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
    ) -> None:
        events = [
            AuditEvent(
                event_type="sampling",
                engagement_id=1,
                user_name="anna",
                sample_id=1,
                details={"filter_operator": "gte", "algorithm_version": "bdo-v1"},
                timestamp=INSIDE_WINDOW,
                id=1,
            )
        ]
        out = tmp_path / "report.html"
        _generator().render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "Filter-Operator: ≥" in html
        assert "filter_operator" not in html


# ---------------------------------------------------------------------------
# Sprint 82 / Befund F – Spalte „Filter" statt „Operator"
# ---------------------------------------------------------------------------


def _sample(sample_id: int, **config: Any) -> SampleResult:
    """Einfache Stichprobe mit frei setzbaren Filter-Feldern der Konfiguration."""
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=7, **config),
        selected_row_ids=(1, 2),
        population_size=10,
        drawn_at=INSIDE_WINDOW,
        id=sample_id,
    )


def _sample_table_cells(html: str) -> dict[str, dict[str, str]]:
    """Stichproben-Tabelle als {"#id": {Spaltenkopf: Zelltext (escaped)}}."""
    section = html.split("<h2>Stichproben</h2>", 1)[1].split("</table>", 1)[0]
    headers = re.findall(r"<th>(.*?)</th>", section)
    rows: dict[str, dict[str, str]] = {}
    for row in re.findall(r"<tr>\s*(<td>#.*?)</tr>", section, re.S):
        cells = re.findall(r"<td>(.*?)</td>", row, re.S)
        rows[cells[0]] = dict(zip(headers, cells, strict=True))
    return rows


def _render(tmp_path: Path, engagement: Engagement, samples: list[SampleResult]) -> str:
    """Rendert den Report mit eingefrorener Uhr und liefert das HTML."""
    out = tmp_path / "report.html"
    _generator().render(engagement, [], samples, [], out)
    return out.read_text(encoding="utf-8")


class TestSampleFilterColumn:
    """Die Stichproben-Tabelle zeigt den Vorfilter als „Feld Operator Wert".

    Vorher stand dort nur das Operator-Symbol: ungefilterte Stichproben zeigten
    „=" (Default-Operator) und waren von „Kostenstelle = Vertrieb" nicht zu
    unterscheiden.
    """

    def test_spalte_heisst_filter_nicht_operator(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        html = _render(tmp_path, engagement, [_sample(1)])
        assert "<th>Filter</th>" in html
        assert "<th>Operator</th>" not in html

    def test_gefilterte_stichprobe_zeigt_feld_operator_wert(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        html = _render(
            tmp_path,
            engagement,
            [
                _sample(1, filter_field="Kostenstelle", filter_value="Vertrieb"),
                _sample(
                    2,
                    filter_field="Betrag",
                    filter_value=100,
                    filter_operator=FilterOperator.GTE,
                ),
            ],
        )
        rows = _sample_table_cells(html)
        assert rows["#1"]["Filter"] == "Kostenstelle = Vertrieb"
        assert rows["#2"]["Filter"] == "Betrag ≥ 100"

    def test_ungefilterte_stichprobe_zeigt_denselben_platzhalter(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        row = _sample_table_cells(_render(tmp_path, engagement, [_sample(1)]))["#1"]
        assert row["Filter"] == "—"
        assert row["Filter"] == row["Parent"]

    def test_ungefilterte_stichprobe_mit_restoperator_zeigt_kein_symbol(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        """Der Sampling-Dialog übernimmt den Operator auch bei „(kein Filter)" –
        maßgeblich ist allein `filter_field is None` (wie `_collect_pool`)."""
        html = _render(tmp_path, engagement, [_sample(1, filter_operator=FilterOperator.GT)])
        assert _sample_table_cells(html)["#1"]["Filter"] == "—"

    def test_filterwert_mit_spitzer_klammer_wird_escaped(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        html = _render(
            tmp_path,
            engagement,
            [_sample(1, filter_field="Kostenstelle", filter_value="<b>Vertrieb</b> & Co")],
        )
        cell = _sample_table_cells(html)["#1"]["Filter"]
        assert cell == "Kostenstelle = &lt;b&gt;Vertrieb&lt;/b&gt; &amp; Co"
        assert "<b>Vertrieb" not in html

    def test_filterwert_none_bei_gesetztem_feld(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        html = _render(tmp_path, engagement, [_sample(1, filter_field="Kostenstelle")])
        assert _sample_table_cells(html)["#1"]["Filter"] == "Kostenstelle = —"

    def test_filter_kommt_aus_der_provenienz(
        self,
        tmp_path: Path,
        engagement: Engagement,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Feld, Symbol und Wert stammen aus EINER `SamplingProvenance` – nicht
        neu aus `sample.config` berechnet."""
        real = SamplingProvenance.from_sample_result

        def _fake(
            result: SampleResult, *, dataset_id: int | None, app_version: str
        ) -> SamplingProvenance:
            return replace(
                real(result, dataset_id=dataset_id, app_version=app_version),
                filter_field="AusProvenienz",
                filter_value="P",
                filter_operator="ne",
            )

        monkeypatch.setattr(SamplingProvenance, "from_sample_result", staticmethod(_fake))
        html = _render(
            tmp_path,
            engagement,
            [_sample(1, filter_field="Kostenstelle", filter_value="Vertrieb")],
        )
        assert _sample_table_cells(html)["#1"]["Filter"] == "AusProvenienz ≠ P"


# ---------------------------------------------------------------------------
# Sprint 74 / Befund D – die zurückgeholte Abdeckung
# ---------------------------------------------------------------------------

_HISTORY_IMG_RE = re.compile(r'data:image/png;base64,([A-Za-z0-9+/=]+)" alt="Sampling-Historie"')


def _history_chart_of(
    tmp_path: Path,
    engagement: Engagement,
    events: list[AuditEvent],
    drawn_at: datetime,
    name: str,
) -> str:
    """Rendert einen Report mit genau einem Sample und liefert dessen
    Historien-Chart als Base64-String zurück."""
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42)
    sample = SampleResult(
        config=cfg,
        selected_row_ids=(1, 2, 3, 4, 5),
        population_size=10,
        drawn_at=drawn_at,
        id=1,
    )
    out = tmp_path / f"{name}.html"
    _generator().render(engagement, [], [sample], events, out)
    match = _HISTORY_IMG_RE.search(out.read_text(encoding="utf-8"))
    assert match is not None, "Historien-Chart fehlt im Report"
    return match.group(1)


class TestSamplingHistoryWindow:
    """Der Test, der seit Ende Mai 2026 still leer lief.

    `test_html_embeds_base64_chart` prüft nur, dass IRGENDEIN PNG eingebettet
    ist – und das ist auch dann erfüllt, wenn das Histogramm eine reine
    Nulllinie zeichnet. Empirisch belegt: das PNG eines Samples von vor
    60 Tagen ist BYTE-IDENTISCH mit dem eines Samples von vor 103 Tagen. Die
    Assertion kann also gar nicht zwischen „Sample geplottet" und „nichts
    geplottet" unterscheiden.

    Die Tests hier prüfen stattdessen die WIRKUNG des Fensters: ein Sample
    innerhalb muss ein anderes Bild erzeugen als eines außerhalb. Wird der
    Histogramm-Zweig entfernt oder neutralisiert, fallen beide auf dieselbe
    Nulllinie zusammen und die Tests werden rot.
    """

    def test_sample_inside_window_changes_the_histogram(
        self,
        tmp_path: Path,
        engagement: Engagement,
        events: list[AuditEvent],
    ) -> None:
        inside = _history_chart_of(tmp_path, engagement, events, INSIDE_WINDOW, "inside")
        outside = _history_chart_of(tmp_path, engagement, events, FIRST_DAY_OUTSIDE, "outside")
        assert inside != outside, (
            "Histogramm ist identisch, egal ob das Sample im 30-Tage-Fenster "
            "liegt – der Zweig wird nicht mehr betreten."
        )

    def test_window_is_half_open_thirty_days(
        self,
        tmp_path: Path,
        engagement: Engagement,
        events: list[AuditEvent],
    ) -> None:
        """Grenzwerte: Tag 29 zählt noch, Tag 30 nicht mehr (`< _HISTORY_DAYS`).

        Fachlogik unverändert (§2.6) – hier nur festgenagelt, damit ein
        späterer Umbau die Fenstergrenze nicht unbemerkt verschiebt.
        """
        last_inside = _history_chart_of(tmp_path, engagement, events, LAST_DAY_INSIDE, "d29")
        first_outside = _history_chart_of(tmp_path, engagement, events, FIRST_DAY_OUTSIDE, "d30")
        far_outside = _history_chart_of(tmp_path, engagement, events, FAR_OUTSIDE, "far")

        assert last_inside != first_outside, "Tag 29 muss noch im Fenster liegen."
        assert first_outside == far_outside, (
            "Alles ab Tag 30 liegt außerhalb und erzeugt dieselbe Nulllinie."
        )

    def test_history_chart_counts_the_sample_on_its_own_day(self) -> None:
        """Direkt auf der Fensterfunktion – ohne Jinja/PNG dazwischen.

        Prüft die Zählung selbst statt ihres gerenderten Bildes: zwei Samples
        am selben Tag landen im selben Bin, eines außerhalb in keinem.
        """
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42)

        def sample_at(when: datetime, sample_id: int) -> SampleResult:
            return SampleResult(
                config=cfg,
                selected_row_ids=(1, 2, 3),
                population_size=10,
                drawn_at=when,
                id=sample_id,
            )

        inside_only = html_report._history_chart_base64([sample_at(INSIDE_WINDOW, 1)], FROZEN_NOW)
        two_inside = html_report._history_chart_base64(
            [sample_at(INSIDE_WINDOW, 1), sample_at(INSIDE_WINDOW, 2)], FROZEN_NOW
        )
        outside_only = html_report._history_chart_base64(
            [sample_at(FIRST_DAY_OUTSIDE, 1)], FROZEN_NOW
        )

        assert inside_only is not None
        assert two_inside is not None
        assert outside_only is not None
        assert inside_only != two_inside, "Zwei Samples am selben Tag müssen höher zählen."
        assert inside_only != outside_only

    def test_no_samples_means_no_history_chart(self) -> None:
        assert html_report._history_chart_base64([], FROZEN_NOW) is None

    def test_default_clock_is_the_real_wall_clock(self) -> None:
        """Ohne `now_provider` bleibt der Produktionspfad an der Wanduhr.

        Bewusst KEIN „Sample von jetzt ist im Fenster"-Test: der würde selbst
        wieder zwei Uhren vergleichen und um Mitternacht kippen (§4.5).
        Geprüft wird die Default-Bindung und dass `_utc_now` UTC liest.
        """
        generator = HtmlReportGenerator()
        assert generator._now_provider is html_report._utc_now

        before = datetime.now(UTC)
        value = html_report._utc_now()
        after = datetime.now(UTC)
        assert before <= value <= after
        assert value.tzinfo is UTC


# ---------------------------------------------------------------------------
# Sprint 83 / A – Spalte „Parent" zeigt die Ableitung
# ---------------------------------------------------------------------------


class TestParentColumnDerivation:
    """Einschränkung und Nachstichprobe sind in der Stichproben-Tabelle
    unterscheidbar; Bestandssamples ohne erfasste Ableitung zeigen nur `#P`."""

    @pytest.mark.parametrize(
        ("relation", "expected"),
        [
            (ParentRelation.RESTRICT, "#17 (eingeschränkt)"),
            (ParentRelation.SUPPLEMENT, "#17 (Nachstichprobe)"),
            (None, "#17"),
        ],
    )
    def test_parent_cell(
        self,
        tmp_path: Path,
        engagement: Engagement,
        relation: ParentRelation | None,
        expected: str,
    ) -> None:
        sample = replace(_sample(1), parent_sample_id=17, parent_relation=relation)
        row = _sample_table_cells(_render(tmp_path, engagement, [sample]))["#1"]
        assert row["Parent"] == expected


# ---------------------------------------------------------------------------
# Sprint 83 / D – der Bericht spricht Deutsch
# ---------------------------------------------------------------------------


def _visible_text(html: str) -> str:
    """Sichtbarer Text: ohne Tags, Attribute, `<style>`/`<script>`-Inhalt."""
    from html.parser import HTMLParser

    class _Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self._hidden = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("style", "script"):
                self._hidden += 1

        def handle_endtag(self, tag: str) -> None:
            if tag in ("style", "script"):
                self._hidden -= 1

        def handle_data(self, data: str) -> None:
            if not self._hidden:
                self.parts.append(data)

    collector = _Collector()
    collector.feed(html)
    return "\n".join(collector.parts)


class TestReportSpeaksGerman:
    def test_no_raw_keys_in_visible_text(self, tmp_path: Path, engagement: Engagement) -> None:
        from tests._readable_reports import raw_words_in, readable_events, readable_samples

        out = tmp_path / "report.html"
        _generator().render(engagement, [], readable_samples(), readable_events(), out)
        text = _visible_text(out.read_text(encoding="utf-8"))

        assert raw_words_in(text) == []
        assert "['" not in text
        for label in (
            "Stichprobe",
            "Rückgängig",
            "Wiederhergestellt",
            "Zurückgesetzt",
            "Einfach",
            "Geschichtet",
            "Schichtungsmodus: Proportional",
            "Kopfzeile: Zeile 5",
            "Spalten: BuchungsID, Belegart",
            "Ableitung: eingeschränkt",
            "Ableitung: Nachstichprobe",
        ):
            assert label in text, label

    def test_method_and_derivation_in_samples_table(
        self, tmp_path: Path, engagement: Engagement
    ) -> None:
        from tests._readable_reports import readable_samples

        rows = _sample_table_cells(_render(tmp_path, engagement, readable_samples()))
        assert "Einfach" in rows["#1"]["Methode"]
        assert "Geschichtet" in rows["#2"]["Methode"]
        assert rows["#2"]["Parent"] == "#1 (eingeschränkt)"
        assert rows["#3"]["Parent"] == "#1 (Nachstichprobe)"
