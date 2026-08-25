"""Der Styling-Vertrag als Test (Sprint 79 / Teil B).

`ui/_scaling.py` setzt Eigenschaften von `bdo_light.qss` voraus, und der
Inline-Styling-Pfad setzt voraus, dass jede feste Schriftgröße durch
`scaled_px()` geht. Bisher sicherte das kein Test ab — und das wird jetzt
wichtig, weil als Nächstes eine Design-Runde an die Optik geht. Fällt dabei eine
dieser Annahmen, wirkt die Einstellung „UI-Größe“ für einzelne Elemente still
nicht mehr; bei Faktor 1,0 (dem Default) sieht alles aus wie immer.

Vier Klassen, vier Aufgaben:

* `TestStylingGuarantees` — jede Zusage gegen die **echten** Dateien.
* `TestPolicyChecksDetectViolations` — je Zusage mindestens eine **Mutation**,
  bei der genau diese Prüffunktion anschlägt. Ohne sie wäre jede grüne Prüfung
  oben nur eine Behauptung: eine Funktion, die immer `[]` zurückgibt, bestünde
  die erste Klasse mühelos.
* `TestScalingReallyScales` — die Gegenprobe am Produktionscode: `scale_stylesheet`
  fasst die zugesagten Stellen tatsächlich an. Der Vertrag beschreibt damit nicht
  nur die Datei, sondern die Wirkung.
* `TestMeasuredValues` — die Ist-Werte, aus denen die Obergrenzen abgeleitet sind.

Der Meta-Test ist **verhaltensbasiert** (§3.3): er ruft die Mutationen auf und
verlangt eine nicht-leere Verstoßliste. Der Sprint-77-Meta-Test prüft per
`inspect.getsource` nur, ob der Funktionsname im Quelltext vorkommt — eine
Prüfung, die bloß in einem Docstring erwähnt wird, käme dort durch.
"""

from __future__ import annotations

from typing import Final

import pytest

from sampling_tool.ui._scaling import (
    UI_SCALE_LEVELS,
    scale_factor,
    scale_stylesheet,
    scaled_px,
)
from tests._styling_policy import (
    HEX_LITERAL_CEILING,
    KNOWN_COLOR_CEILINGS,
    LOGO_SELECTOR,
    MIN_QSS_BLOCKS,
    MIN_UI_SOURCE_FILES,
    QSS_CHECKS,
    SOURCE_CHECK_NEEDS_PACKAGE,
    SOURCE_CHECKS,
    QssCheck,
    SourceCheck,
    check_blocks_are_flat,
    check_font_sizes_are_integer_px,
    check_hex_literals_do_not_grow,
    check_inline_font_sizes_are_scaled,
    check_logo_block_is_scalable,
    check_sources_are_not_vacuous,
    check_stylesheet_is_not_vacuous,
    count_hex_literals,
    font_size_declarations,
    hex_literal_histogram,
    package_sources,
    registered_checks,
    run_qss_checks,
    run_source_checks,
    strip_comments,
    stylesheet_path,
    stylesheet_text,
    ui_sources,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures & Mutations-Werkzeug
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qss() -> str:
    return stylesheet_text()


@pytest.fixture(scope="module")
def ui() -> dict[str, str]:
    return ui_sources()


@pytest.fixture(scope="module")
def package() -> dict[str, str]:
    return package_sources()


def replaced(text: str, old: str, new: str) -> str:
    """`old` → `new`, aber mit hartem Fehler, wenn `old` nicht (mehr) vorkommt.

    Der harte Fehler ist Absicht (Muster aus Sprint 77): findet eine Mutation
    ihren Angriffspunkt nicht mehr, ist die Positiv-Kontrolle wertlos geworden
    und muss auffallen, statt still auf einem unveränderten Text grün zu bleiben.
    """
    assert old in text, f"Mutations-Anker {old!r} nicht mehr im Text gefunden"
    return text.replace(old, new, 1)


def a_file_with_scaled_font_size(sources: dict[str, str]) -> str:
    """Pfad einer Datei mit einer skalierten Inline-`font-size` – sonst harter Fehler."""
    for path, content in sorted(sources.items()):
        if any("scaled_px(" in value for _line, value in font_size_declarations(content)):
            return path
    raise AssertionError("Keine Datei mit skalierter Inline-font-size gefunden")


def with_unscaled_font_size(sources: dict[str, str]) -> dict[str, str]:
    """Eine skalierte Inline-`font-size` durch eine feste Zahl ersetzen."""
    path = a_file_with_scaled_font_size(sources)
    content = sources[path]
    for _line, value in font_size_declarations(content):
        if "scaled_px(" in value:
            return {**sources, path: replaced(content, f"font-size: {value}", "font-size: 11px")}
    raise AssertionError("Unerreichbar – a_file_with_scaled_font_size hat gefiltert")


def without_logo_bounds(qss: str) -> str:
    """Alle min/max-Grenzwerte aus dem Logo-Block entfernen.

    Jede der vier Ersetzungen läuft über `replaced` und schlägt einzeln fehl,
    wenn sie ihren Anker verliert – eine stille No-Op-Ersetzung würde die
    Mutation abschwächen, ohne dass jemand es merkt.

    Die Anker enthalten bewusst KEIN `\\n`: sonst hinge die Positiv-Kontrolle an
    den Zeilenenden des Checkouts (`.gitattributes` erzwingt hier zwar LF, aber
    ein Test soll nicht von einer Einstellung woanders abhängen).
    """
    for bound in ("min-width", "min-height", "max-width", "max-height"):
        qss = replaced(qss, f"{bound}: 120px;", "")
    return qss


def with_extra_hex(sources: dict[str, str], literal: str, times: int = 1) -> dict[str, str]:
    """`times` zusätzliche Hex-Literale in eine beliebige, stabile Datei schreiben."""
    path = sorted(sources)[0]
    addition = "\n" + "\n".join(f'_NEUE_FARBE_{i} = "{literal}"' for i in range(times))
    return {**sources, path: sources[path] + addition}


#: Je Zusage mindestens eine Mutation, die sie brechen MUSS.
#: `(Bezeichnung, Eingabe)` – die Eingabe ist immer ein mutierter String bzw. ein
#: mutiertes Mapping, nie eine geänderte Datei (§3.3).
def qss_mutations(qss: str) -> dict[QssCheck, list[tuple[str, str]]]:
    return {
        check_stylesheet_is_not_vacuous: [
            ("leere Datei", ""),
            ("nur Kommentar", "/* alles weg */\n"),
        ],
        check_font_sizes_are_integer_px: [
            ("relative Einheit em", replaced(qss, "font-size: 13px", "font-size: 0.9em")),
            ("Dezimalwert", replaced(qss, "font-size: 13px", "font-size: 13.5px")),
            ("Punkt statt Pixel", replaced(qss, "font-size: 13px", "font-size: 10pt")),
            (
                "Leerzeichen vor dem Doppelpunkt",
                replaced(qss, "font-size: 13px", "font-size : 13px"),
            ),
        ],
        check_blocks_are_flat: [
            (
                "verschachtelter Block",
                replaced(
                    qss,
                    "QMenuBar::item {",
                    "QMenuBar::item {\n    QLabel { color: #333333; }",
                ),
            ),
        ],
        check_logo_block_is_scalable: [
            (
                "Selektor umbenannt",
                replaced(qss, f"{LOGO_SELECTOR} {{", "QLabel#BrandMark {"),
            ),
            (
                "Selektor in einer Liste",
                replaced(
                    qss,
                    f"{LOGO_SELECTOR} {{",
                    f"{LOGO_SELECTOR},\nQLabel#WelcomeBadge {{",
                ),
            ),
            ("Grenzwerte ausgezogen", without_logo_bounds(qss)),
        ],
    }


def source_mutations(
    ui: dict[str, str], package: dict[str, str]
) -> dict[SourceCheck, list[tuple[str, dict[str, str]]]]:
    known_color = next(iter(KNOWN_COLOR_CEILINGS))
    return {
        check_sources_are_not_vacuous: [
            ("leere Menge", {}),
            ("eine Datei übrig", {sorted(ui)[0]: ui[sorted(ui)[0]]}),
        ],
        check_inline_font_sizes_are_scaled: [
            ("feste Zahl statt scaled_px", with_unscaled_font_size(package)),
            ("gar keine Inline-font-size mehr", {"leer.py": "x = 1\n"}),
        ],
        check_hex_literals_do_not_grow: [
            ("eine neue Farbe", with_extra_hex(ui, "#123456")),
            (f"eine Farbe mehr, für die es {known_color} gibt", with_extra_hex(ui, known_color)),
        ],
    }


# ---------------------------------------------------------------------------
# 1. Die Zusagen gegen die echten Dateien
# ---------------------------------------------------------------------------


class TestStylingGuarantees:
    """Jede Zusage, die eine Design-Runde still brechen kann, gegen die echte Datei."""

    def test_stylesheet_exists_where_the_app_looks_for_it(self) -> None:
        """Der Pfad kommt über `package_resource`, nicht über ein Pfad-Literal –
        sonst prüfte der Test eine andere Datei als die, die die App lädt."""
        assert stylesheet_path().exists(), stylesheet_path()

    def test_stylesheet_is_not_vacuous(self, qss: str) -> None:
        assert check_stylesheet_is_not_vacuous(qss) == []

    def test_all_font_sizes_are_integer_px(self, qss: str) -> None:
        """`0.9em` / `13.5px` / `10pt` würde `_FONT_SIZE_RE` nicht mehr greifen."""
        assert check_font_sizes_are_integer_px(qss) == []

    def test_no_nested_blocks(self, qss: str) -> None:
        """Die Non-Greedy-Annahme von `_LOGO_BLOCK_RE` (`.*?` bis zur ersten `}`)."""
        assert check_blocks_are_flat(qss) == []

    def test_logo_block_exists_and_carries_bounds(self, qss: str) -> None:
        assert check_logo_block_is_scalable(qss) == []

    def test_sources_are_not_vacuous(self, ui: dict[str, str]) -> None:
        assert check_sources_are_not_vacuous(ui) == []

    def test_every_inline_font_size_is_scaled(self, package: dict[str, str]) -> None:
        """Eine feste Zahl in einem f-String ist kein Fehler und keine Warnung –
        das Element ignoriert die UI-Größe danach einfach."""
        assert check_inline_font_sizes_are_scaled(package) == []

    def test_hex_literals_do_not_grow(self, ui: dict[str, str]) -> None:
        assert check_hex_literals_do_not_grow(ui) == []

    def test_every_promise_holds_at_once(
        self, qss: str, ui: dict[str, str], package: dict[str, str]
    ) -> None:
        """Der Sammel-Lauf: keine einzige Zusage ist verletzt."""
        assert run_qss_checks(qss) == []
        assert run_source_checks(ui, package) == []


# ---------------------------------------------------------------------------
# 2. Positiv-Kontrollen: jede Zusage muss ihren Bruch bemerken
# ---------------------------------------------------------------------------


class TestPolicyChecksDetectViolations:
    """Für jede Zusage mindestens eine Mutation, die einen Verstoß auslösen MUSS.

    Mutiert wird ausschließlich in-memory: kein Wegwerf-Branch, keine angefasste
    Datei, kein CI-Lauf.
    """

    def test_every_registered_check_has_a_working_positive_control(
        self, qss: str, ui: dict[str, str], package: dict[str, str]
    ) -> None:
        """Der Meta-Test, verhaltensbasiert (§3.3).

        Verlangt wird nicht, dass der Funktionsname irgendwo im Quelltext dieser
        Datei auftaucht (so prüft es Sprint 77 – ein Name in einem Docstring käme
        damit durch), sondern dass eine Mutation existiert, bei der GENAU DIESE
        Funktion eine nicht-leere Liste liefert. Der Test ruft sie dafür auf.
        """
        controls: dict[str, list[tuple[str, list[str]]]] = {}
        for check, cases in qss_mutations(qss).items():
            controls[check.__name__] = [(label, check(mutated)) for label, mutated in cases]
        for source_check, source_cases in source_mutations(ui, package).items():
            controls[source_check.__name__] = [
                (label, source_check(mutated)) for label, mutated in source_cases
            ]

        registered = {check.__name__ for check in registered_checks()}
        assert registered == set(controls), (
            f"Ohne Positiv-Kontrolle: {sorted(registered - set(controls))}; "
            f"Kontrolle ohne Registry-Eintrag: {sorted(set(controls) - registered)}"
        )
        toothless = sorted(
            name
            for name, results in controls.items()
            if not any(violations for _label, violations in results)
        )
        assert toothless == [], f"Zusagen, deren Mutation nichts auslöst: {toothless}"

    def test_registry_covers_both_families(self) -> None:
        """Anti-Vakuum für den Meta-Test: über einer leeren Registry hätte er
        nichts zu prüfen und wäre mühelos grün.

        `>=`, nicht `==`: eine neue Zusage soll nichts rot machen (der Meta-Test
        verlangt ohnehin sofort eine Positiv-Kontrolle dafür), eine gelöschte
        schon.
        """
        assert len(QSS_CHECKS) >= 4
        assert len(SOURCE_CHECKS) >= 3
        assert len(registered_checks()) == len(QSS_CHECKS) + len(SOURCE_CHECKS)

    def test_every_source_check_declares_its_scope(self) -> None:
        """`run_source_checks` schlägt eine Prüfung ohne Scope-Eintrag mit
        `KeyError` – laut, aber erst zur Laufzeit. Hier steht es als Zusage."""
        assert {check.__name__ for check in SOURCE_CHECKS} == set(SOURCE_CHECK_NEEDS_PACKAGE)

    @pytest.mark.parametrize(
        ("check_name", "label"),
        [
            (check.__name__, label)
            for check, cases in qss_mutations(stylesheet_text()).items()
            for label, _mutated in cases
        ],
    )
    def test_each_qss_mutation_is_rejected(self, qss: str, check_name: str, label: str) -> None:
        """Jede einzelne Mutation einzeln sichtbar – damit im Fehlerfall dransteht,
        WELCHE Bruchstelle nicht mehr auffällt."""
        for check, cases in qss_mutations(qss).items():
            if check.__name__ != check_name:
                continue
            for case_label, mutated in cases:
                if case_label == label:
                    assert check(mutated), f"{check_name} / {label}"
                    return
        raise AssertionError(f"Mutation {check_name} / {label} nicht gefunden")

    @pytest.mark.parametrize(
        ("check_name", "label"),
        [
            (check.__name__, label)
            for check, cases in source_mutations(ui_sources(), package_sources()).items()
            for label, _mutated in cases
        ],
    )
    def test_each_source_mutation_is_rejected(
        self, ui: dict[str, str], package: dict[str, str], check_name: str, label: str
    ) -> None:
        for check, cases in source_mutations(ui, package).items():
            if check.__name__ != check_name:
                continue
            for case_label, mutated in cases:
                if case_label == label:
                    assert check(mutated), f"{check_name} / {label}"
                    return
        raise AssertionError(f"Mutation {check_name} / {label} nicht gefunden")

    def test_unmutated_input_triggers_nothing(
        self, qss: str, ui: dict[str, str], package: dict[str, str]
    ) -> None:
        """Die Gegenrichtung: eine Prüfung, die immer meldet, wäre genauso wertlos
        wie eine, die nie meldet."""
        for check in QSS_CHECKS:
            assert check(qss) == [], check.__name__
        assert check_sources_are_not_vacuous(ui) == []
        assert check_inline_font_sizes_are_scaled(package) == []
        assert check_hex_literals_do_not_grow(ui) == []

    def test_hex_ratchet_allows_shrinking(self, ui: dict[str, str]) -> None:
        """Der Ratchet zeigt NACH UNTEN: Sprint 80 wird die 33 Literale ersetzen,
        für die es schon eine Konstante gibt. Das darf nicht rot werden."""
        fewer = {
            path: content.replace(next(iter(KNOWN_COLOR_CEILINGS)), "X")
            for path, content in ui.items()
        }
        assert check_hex_literals_do_not_grow(fewer) == []

    def test_comment_in_the_qss_is_not_mistaken_for_a_declaration(self, qss: str) -> None:
        """Beide Prüfungen laufen über `strip_comments`.

        Die Datei ist dicht kommentiert, und die Kommentare zitieren QSS-Syntax
        (Farbwerte, Selektoren, ganze Regeln). Ohne das Entfernen prüfte die
        Funktion die Begründung statt der Zeile.
        """
        commented = f"/* Beispiel: font-size: 0.9em; und ein QLabel {{ }} */\n{qss}"
        assert check_font_sizes_are_integer_px(commented) == []
        assert check_blocks_are_flat(commented) == []


# ---------------------------------------------------------------------------
# 3. Die Gegenprobe am Produktionscode
# ---------------------------------------------------------------------------


class TestScalingReallyScales:
    """Der Vertrag beschreibt nicht nur die Datei, sondern die Wirkung.

    Die Prüfungen oben belegen, dass die Datei die Form hat, die
    `scale_stylesheet` erwartet. Hier steht die andere Hälfte: dass die Funktion
    diese Form auch tatsächlich in eine Änderung übersetzt — an ALLEN zugesagten
    Stellen, nicht an einer.
    """

    def test_every_font_size_actually_changes(self, qss: str) -> None:
        factor = scale_factor("groß")
        scaled = scale_stylesheet(qss, factor)
        before = [value for _line, value in font_size_declarations(strip_comments(qss))]
        after = [value for _line, value in font_size_declarations(strip_comments(scaled))]
        assert len(before) == len(after)
        expected = [f"{scaled_px(int(value.removesuffix('px')), factor)}px" for value in before]
        assert after == expected
        # Nicht-Trivialität: bei Faktor 1.0 wäre die Zusage oben leer erfüllt.
        assert after != before

    def test_every_logo_bound_actually_changes(self, qss: str) -> None:
        """Die vier min/max-Grenzwerte des Logo-Blocks bewegen sich mit."""
        factor = scale_factor("groß")
        scaled = scale_stylesheet(qss, factor)
        for base in ("min-width", "min-height", "max-width", "max-height"):
            assert f"{base}: 120px" in qss
            assert f"{base}: {scaled_px(120, factor)}px" in scaled

    def test_scrollbar_bounds_stay_untouched(self, qss: str) -> None:
        """Die Gegenprobe zur Block-Isolierung: `_LOGO_BOUND_RE` gilt NUR im
        Logo-Block. Der QScrollBar-Handle nutzt dieselben Property-Namen und
        bleibt bewusst unskaliert – griffe das Muster global, wäre das hier rot."""
        scaled = scale_stylesheet(qss, scale_factor("groß"))
        assert "min-height: 30px" in scaled
        assert "min-width: 30px" in scaled

    @pytest.mark.parametrize("level", UI_SCALE_LEVELS)
    def test_contract_holds_at_every_level(self, qss: str, level: str) -> None:
        """Das skalierte Stylesheet erfüllt den Vertrag selbst wieder.

        Sonst wäre „groß“ ein Einbahnstraßen-Zustand: eine Skalierung, die
        `13px` zu `14.95px` machte, bräche die eigene Voraussetzung – und die
        nächste Anwendung (Settings-Dialog, live) fände nichts mehr.
        """
        assert run_qss_checks(scale_stylesheet(qss, scale_factor(level))) == []


# ---------------------------------------------------------------------------
# 4. Die gemessenen Ist-Werte
# ---------------------------------------------------------------------------


class TestMeasuredValues:
    """Die Zahlen, aus denen die Obergrenzen abgeleitet sind – Stand Sprint 79.

    Bewusst als Richtung mit Abstand, nicht als Gleichheit. Ein Test, der auf
    `== 61 Blöcke` oder `== 7 font-size` besteht, wird von der nächsten
    Design-Runde aus dem falschen Grund rot gemacht – und dann entschärft. Die
    Ist-Werte stehen als Messung in `tests/_styling_policy.py`; hier steht nur,
    was aus ihnen folgen muss.
    """

    #: Gemessen 2026-08-25 auf `main` = d8417d3 (Sprint 78): 33 der 53 rohen
    #: Literale sind eine Farbe, für die `config.py` schon eine Konstante hat.
    #: Der Auftrag für Sprint 80 – und damit eine Zahl, die SINKEN soll.
    REPLACEABLE_TODAY: Final[int] = 33

    def test_current_state_stays_under_the_ceiling(self, ui: dict[str, str]) -> None:
        assert sum(count_hex_literals(content) for content in ui.values()) <= HEX_LITERAL_CEILING

    def test_known_colors_are_the_bulk_of_the_debt(self, ui: dict[str, str]) -> None:
        """Die Literale mit vorhandener Konstante werden nicht mehr.

        `<=`, nicht `==`: Sprint 80 wird sie ersetzen, und ein Test, der dessen
        Erfolg rot macht, wäre genau der Test, den danach jemand löscht.
        """
        histogram = hex_literal_histogram(ui)
        replaceable = sum(histogram.get(color.upper(), 0) for color in KNOWN_COLOR_CEILINGS)
        assert 0 < replaceable <= self.REPLACEABLE_TODAY

    def test_anti_vacuum_floors_sit_well_below_reality(self, ui: dict[str, str]) -> None:
        """Die Anti-Vakuum-Grenzen fangen das Vakuum ab, nicht das Schrumpfen –
        sie müssen deutlich unter dem Ist-Stand liegen (Sprint-78-Lehre: kein
        Test mit knapper Reserve an einer Grenze)."""
        assert len(ui) > MIN_UI_SOURCE_FILES
        assert strip_comments(stylesheet_text()).count("{") > MIN_QSS_BLOCKS

    def test_the_qss_has_something_to_scale(self, qss: str) -> None:
        """Kein Pin auf 7 – nur: es gibt überhaupt Deklarationen, über die der
        Vertrag redet."""
        assert font_size_declarations(strip_comments(qss))
