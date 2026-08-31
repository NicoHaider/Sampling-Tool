"""Prüffunktionen für den Styling-Vertrag (Sprint 79 / Teil B).

Zwischen dem Styling und dem Code, der es skaliert, steht ein ungeschriebener
Vertrag. `ui/_scaling.py::scale_stylesheet` setzt Eigenschaften von
`bdo_light.qss` voraus — ganzzahlige px-Werte, flache Blöcke, einen Block namens
`QLabel#LogoPlaceholder` —, und der Inline-Styling-Pfad in `ui/**/*.py` setzt
voraus, dass jede feste Schriftgröße durch `scaled_px()` geht.

Bricht eine dieser Annahmen, passiert **nichts Sichtbares**: bei Faktor 1,0
(`ui_scale = "normal"`, der Default) sieht alles aus wie immer. Erst wer „groß"
oder „klein" wählt, sieht ein Element, das sich nicht mitbewegt — und selbst dann
sieht es nicht nach einem Fehler aus, sondern nach einer Design-Entscheidung.
Genau deshalb steht der Vertrag hier und nicht in einem Kommentar.

Bauweise, dem Muster von `tests/_workflow_policy.py` (Sprint 77) folgend:

* Jede Prüfung ist eine **reine Funktion über dem Datei-INHALT** (ein String bzw.
  ein `{Pfad: Inhalt}`-Mapping), nie über einem Pfad. Nur so kann die
  Positiv-Kontrolle einen mutierten String übergeben, ohne eine Datei anzufassen.
  Die Pfade im Mapping sind Beschriftung für die Meldung, kein Lesezugriff.
* Jede gibt eine **Liste von Verstoß-Meldungen** zurück; leer = Zusage gehalten.
* Die Muster, gegen die geprüft wird, werden **aus dem Produktionscode
  importiert** (`_FONT_SIZE_RE`, `_LOGO_BLOCK_RE`, `_LOGO_BOUND_RE`) statt hier
  nachgetippt. Die Zusage ist damit per Konstruktion deckungsgleich mit dem, was
  `scale_stylesheet` tatsächlich anfasst — ein nachgetipptes Muster könnte
  auseinanderlaufen und die Prüfung würde die falsche Frage beantworten.
* Die bekannten Farben kommen aus `sampling_tool.config`, nicht als Hex-Literal
  (dieselbe Regel, aus der in Sprint 72 die `"groß"`-Falle wurde).

Die Zusagen selbst stehen in den Docstrings der `check_*`-Funktionen: wer eine
Eigenschaft aufgeben will, liest dort zuerst, was daran hängt.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

from sampling_tool.config import (
    BDO_DARK_GREY,
    BDO_GREY,
    BDO_LIGHT_GREY,
    BDO_RED,
    WARNING_COLOR,
)
from sampling_tool.resources import package_resource

# Die Muster, die `scale_stylesheet` tatsächlich anwendet – importiert, nicht
# nachgetippt (siehe Modul-Docstring).
from sampling_tool.ui._scaling import _FONT_SIZE_RE, _LOGO_BLOCK_RE, _LOGO_BOUND_RE

#: Eine Zusage über dem Stylesheet-Text bzw. über einem `{Pfad: Inhalt}`-Mapping.
QssCheck: TypeAlias = Callable[[str], list[str]]
SourceCheck: TypeAlias = Callable[[dict[str, str]], list[str]]

#: Relativer Resource-Pfad des Stylesheets. Wird über `package_resource` aufgelöst
#: (§3.3) – ein Pfad-Literal wäre im PyInstaller-Bundle falsch und hier eine
#: zweite Wahrheit über denselben Ort.
STYLESHEET_RESOURCE: Final[str] = "ui/styles/bdo_light.qss"

#: Der Selektor, dessen Block `scale_stylesheet` isoliert. Aus dem Muster
#: abgeleitet statt daneben getippt.
LOGO_SELECTOR: Final[str] = "QLabel#LogoPlaceholder"

#: `_scaling.py` ist von der Inline-Prüfung ausgenommen: das `font-size:` darin
#: ist das SUCHMUSTER, keine Deklaration. Wird das Modul umbenannt, meldet die
#: Prüfung einen Verstoß – laut und sofort, nicht still.
SCALING_MODULE: Final[str] = "_scaling.py"

#: `_fonts.py` ist die einzige Stelle, die eine QFont-GRÖSSE setzen darf –
#: gespiegelt zu `SCALING_MODULE` für `font-size:` im Stylesheet. Wird das Modul
#: umbenannt, schlägt die Zusage an, statt die Ausnahme still zu verlieren.
FONTS_MODULE: Final[str] = "_fonts.py"

#: Größen-Setter auf einer `QFont`. Nur im Helfer erlaubt.
_FONT_SIZE_SETTERS: Final[frozenset[str]] = frozenset(
    {"setPointSize", "setPointSizeF", "setPixelSize"}
)

#: Größen-Abfragen, auf denen gerechnet zu werden pflegt – und genau dort bricht es.
_FONT_SIZE_GETTERS: Final[frozenset[str]] = frozenset({"pointSize", "pointSizeF", "pixelSize"})

#: Anti-Vakuum-Grenzen. Eine Prüfung über einer leeren Menge ist keine Prüfung:
#: „alle font-size sind ganzzahlig" ist über null Deklarationen trivial wahr.
#: Die Zahlen liegen bewusst WEIT unter dem Ist-Stand – sie fangen das Vakuum ab,
#: nicht das normale Wachsen und Schrumpfen einer Datei.
MIN_QSS_BLOCKS: Final[int] = 30  # gemessen 2026-08-25: 61
MIN_UI_SOURCE_FILES: Final[int] = 25  # gemessen 2026-08-25: 50

#: Obergrenze roher Hex-Literale in `ui/**/*.py` – ein Ratchet NACH UNTEN.
#: Der Wert darf sinken, nie steigen: jede neue Farbe direkt im Code statt über
#: eine Konstante macht die Palette wieder zu etwas, das an vielen Stellen
#: gleichzeitig geändert werden müsste.
#:
#: Sprint 79 maß 53. Sprint 80 hat die 33 Literale mit vorhandener Konstante
#: ersetzt und drei Warn-Labels auf `WARNING_COLOR` gelegt: 53 − 33 − 3 = 17.
#:
#: 17 ist der Boden, den reine Konstanten-Ersetzung erreichen kann. Die
#: verbleibenden Literale sind eine DESIGN-Frage, keine Mechanik (fünf Grautöne,
#: drei fast identische Off-Whites) – und eines davon, `#F4F4F4` in
#: `main_window.py`, steht in einem KOMMENTAR: die Prüfung zählt den rohen
#: Dateiinhalt ohne Kommentar-Entfernung, eine Konstante kann es also gar nicht
#: ersetzen. Wer unter 17 will, muss dort den Text ändern.
#:
#: Gemessen 2026-08-25 (Sprint 80), `src/sampling_tool/ui/**/*.py`: 17.
HEX_LITERAL_CEILING: Final[int] = 17

#: Je Farbe, für die es in `config.py` eine Konstante gibt. Einzeln, damit ein
#: Anstieg bei einer Farbe auffällt und nicht nur in der Summe – 19 → 20 bei
#: gleichzeitigem 7 → 6 wäre in der Gesamtzahl unsichtbar.
#:
#: Seit Sprint 80 stehen alle auf **0**: für diese Farben ist ein rohes Literal
#: im Code kein „noch nicht aufgeräumt" mehr, sondern ein Rückschritt.
#: Gemessen 2026-08-25 (Sprint 80).
KNOWN_COLOR_CEILINGS: Final[dict[str, int]] = {
    BDO_GREY: 0,
    BDO_DARK_GREY: 0,
    BDO_RED: 0,
    BDO_LIGHT_GREY: 0,
    WARNING_COLOR: 0,
}

#: `#RRGGBB`; die Lookahead-Grenze verhindert, dass die ersten sechs Stellen einer
#: längeren Zeichenkette (`#1234567`) als Farbe gezählt werden. Drei- und
#: achtstellige Formen kommen im Projekt nicht vor (geprüft) – `#102` in einer
#: PR-Referenz ist deshalb kein Treffer.
HEX_LITERAL_RE: Final[re.Pattern[str]] = re.compile(r"#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])")

#: Findet `font-size`-Deklarationen TOLERANT – auch die kaputten Formen, die
#: `_FONT_SIZE_RE` nicht mehr greifen würde (`0.9em`, `13.5px`, `10pt`, und auch
#: `font-size : 13px` mit Leerzeichen vor dem Doppelpunkt). Genau darin liegt der
#: Sinn: was diese Regex findet und die Produktions-Regex nicht, ist der Verstoß.
LENIENT_FONT_SIZE_RE: Final[re.Pattern[str]] = re.compile(r"font-size\s*:\s*([^;}\n\"']*)")

_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"/\*.*?\*/", re.DOTALL)


# ---------------------------------------------------------------------------
# Laden – die einzigen Funktionen hier, die das Dateisystem anfassen
# ---------------------------------------------------------------------------


def stylesheet_path() -> Path:
    return package_resource(STYLESHEET_RESOURCE)


def stylesheet_text() -> str:
    """Der Inhalt von `bdo_light.qss` – so, wie `load_scaled_stylesheet` ihn liest."""
    return stylesheet_path().read_text(encoding="utf-8")


def _sources_under(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.py"))
    }


def ui_sources() -> dict[str, str]:
    """`{relativer Pfad: Inhalt}` aller Python-Dateien unter `ui/`."""
    return _sources_under(package_resource("ui"))


def package_sources() -> dict[str, str]:
    """`{relativer Pfad: Inhalt}` aller Python-Dateien des Pakets.

    Weiter gefasst als `ui_sources()`, weil die Zusage „jede Inline-`font-size`
    geht durch `scaled_px`" für `src/` insgesamt gilt: ein Stylesheet-String
    könnte auch außerhalb von `ui/` entstehen, und dort fiele er niemandem auf.
    """
    return _sources_under(package_resource(""))


# ---------------------------------------------------------------------------
# Hilfsfunktionen über dem Inhalt
# ---------------------------------------------------------------------------


def strip_comments(qss: str) -> str:
    """Ersetzt `/* … */` durch Leerraum – Zeilennummern bleiben erhalten.

    Nicht gelöscht, sondern überschrieben: eine Meldung, die auf die falsche
    Zeile zeigt, kostet beim Suchen mehr, als die Prüfung an Zeit spart. Die
    Kommentare selbst müssen raus, weil sie QSS-Syntax zitieren dürfen, ohne sie
    zu sein.
    """
    return _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), qss)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def count_hex_literals(content: str) -> int:
    return len(HEX_LITERAL_RE.findall(content))


def hex_literal_histogram(sources: dict[str, str]) -> dict[str, int]:
    """Wie oft jede Farbe vorkommt – Groß-/Kleinschreibung normalisiert."""
    histogram: dict[str, int] = {}
    for content in sources.values():
        for literal in HEX_LITERAL_RE.findall(content):
            key = literal.upper()
            histogram[key] = histogram.get(key, 0) + 1
    return histogram


def font_size_declarations(content: str) -> list[tuple[int, str]]:
    """`(Zeile, Wert)` je gefundener `font-size`-Deklaration, tolerant gefunden."""
    return [
        (line_of(content, match.start()), match.group(1).strip())
        for match in LENIENT_FONT_SIZE_RE.finditer(content)
    ]


# ---------------------------------------------------------------------------
# Zusagen der QSS-Datei (§3.1)
# ---------------------------------------------------------------------------


def check_stylesheet_is_not_vacuous(qss: str) -> list[str]:
    """Anti-Vakuum: das Stylesheet hat überhaupt Inhalt.

    Ohne diese Prüfung wären alle folgenden über einer leeren Datei zufrieden –
    und eine leere Datei ist der schlimmste denkbare Zustand dieses Vertrags:
    `load_scaled_stylesheet` liefert dann still `""`, die App fällt auf das
    System-Theme zurück und KEIN Test wird rot.
    """
    blocks = strip_comments(qss).count("{")
    if blocks >= MIN_QSS_BLOCKS:
        return []
    return [
        f"bdo_light.qss hat nur {blocks} Blöcke, erwartet mindestens "
        f"{MIN_QSS_BLOCKS} – über einer leeren oder fast leeren Datei sind alle "
        f"anderen Styling-Zusagen trivial erfüllt (Sprint 79)."
    ]


def check_font_sizes_are_integer_px(qss: str) -> list[str]:
    """Sprint 68/79: jede `font-size`-Deklaration ist ganzzahlig in px.

    `_FONT_SIZE_RE` greift ausschließlich auf `font-size:<n>px` mit ganzzahligem
    `n`. `0.9em`, `13.5px`, `10pt` oder ein Leerzeichen vor dem Doppelpunkt
    werden von `scale_stylesheet` schlicht nicht gefunden – die Einstellung
    „UI-Größe" wirkt für dieses eine Element dann nicht mehr, ohne Fehlermeldung
    und bei Faktor 1,0 ohne sichtbaren Unterschied.

    Geprüft wird gegen die IMPORTIERTE Produktions-Regex: gefragt ist nicht
    „sieht der Wert plausibel aus", sondern „fasst `scale_stylesheet` ihn an".
    """
    violations = []
    cleaned = strip_comments(qss)
    found = 0
    for match in LENIENT_FONT_SIZE_RE.finditer(cleaned):
        found += 1
        value = match.group(1).strip()
        # An DERSELBEN Stelle im Originaltext ansetzen, nicht auf einer
        # normalisierten Kopie: sonst repariert die Prüfung genau die Abweichung,
        # die sie finden soll (`font-size : 13px` sähe nach `font-size: 13px` aus).
        strict = _FONT_SIZE_RE.match(cleaned, match.start())
        if strict is not None and value.startswith(f"{strict.group(2)}{strict.group(3)}"):
            continue
        violations.append(
            f"bdo_light.qss Zeile {line_of(cleaned, match.start())}: font-size ist "
            f"{value!r} – erwartet ist eine ganze Zahl in px (z. B. '13px'), direkt "
            f"hinter dem Doppelpunkt. scale_stylesheet() findet diesen Wert nicht, "
            f"die UI-Größe wirkt hier still nicht mehr (Sprint 68/79)."
        )
    if found == 0:
        violations.append(
            "bdo_light.qss enthält keine einzige font-size-Deklaration – über einer "
            "leeren Menge ist die Zusage trivial erfüllt (Sprint 79)."
        )
    return violations


def check_blocks_are_flat(qss: str) -> list[str]:
    """Sprint 68/79: kein `{` innerhalb eines Blocks.

    `_LOGO_BLOCK_RE` isoliert den LogoPlaceholder-Block mit einem non-greedy
    `(.*?)` bis zur ERSTEN `}`. Das ist genau dann korrekt, wenn QSS-Blöcke flach
    sind. Käme je ein verschachtelter Block dazu (Qt kennt das nicht, ein
    Präprozessor oder eine versehentlich nicht geschlossene Klammer schon), endete
    der isolierte Body an der falschen Stelle und die min/max-Grenzwerte des Logos
    würden entweder gar nicht oder in einem fremden Block skaliert.
    """
    violations = []
    depth = 0
    for offset, char in enumerate(strip_comments(qss)):
        if char == "{":
            depth += 1
            if depth > 1:
                violations.append(
                    f"bdo_light.qss Zeile {line_of(qss, offset)}: verschachteltes '{{' – "
                    f"_LOGO_BLOCK_RE isoliert den LogoPlaceholder-Block bis zur ersten "
                    f"'}}' und träfe damit den falschen Block (Sprint 68/79)."
                )
        elif char == "}":
            depth -= 1
            if depth < 0:
                violations.append(
                    f"bdo_light.qss Zeile {line_of(qss, offset)}: '}}' ohne offenes "
                    f"'{{' – die Blockstruktur ist unausgeglichen (Sprint 79)."
                )
                depth = 0
    if depth != 0:
        violations.append(
            f"bdo_light.qss: {depth} Block(s) am Dateiende nicht geschlossen – die "
            f"Blockstruktur ist unausgeglichen (Sprint 79)."
        )
    return violations


def check_logo_block_is_scalable(qss: str) -> list[str]:
    """Sprint 68/79: der `QLabel#LogoPlaceholder`-Block existiert und trägt Grenzwerte.

    Drei Wege, auf denen diese Zusage bricht, und alle drei sind still:

    1. Der Selektor wird umbenannt – `_LOGO_BLOCK_RE` greift nirgends mehr.
    2. Der Selektor wandert in eine Selektor-LISTE (`QLabel#LogoPlaceholder,
       QLabel#Anderes { … }`). Der Text steht dann noch da, aber `\\s*\\{` passt
       nicht mehr: die Umbenennungs-Prüfung allein würde das übersehen.
    3. Der Block bleibt, aber die min/max-Grenzwerte ziehen aus. Dann skaliert
       `_LOGO_BOUND_RE` einen leeren Body, und das Logo behält seine 120px, während
       die Schrift darin größer wird.
    """
    cleaned = strip_comments(qss)
    blocks = _LOGO_BLOCK_RE.findall(cleaned)
    mentions = cleaned.count(LOGO_SELECTOR)

    if not blocks:
        return [
            f"bdo_light.qss: kein Block '{LOGO_SELECTOR} {{ … }}' gefunden "
            f"({mentions} Erwähnung(en) des Selektors) – _LOGO_BLOCK_RE greift "
            f"nirgends, die min/max-Grenzwerte des Logos skalieren nicht mehr "
            f"(Sprint 68/79)."
        ]

    violations = []
    if len(blocks) != mentions:
        violations.append(
            f"bdo_light.qss: '{LOGO_SELECTOR}' kommt {mentions}× vor, aber nur "
            f"{len(blocks)}× als eigener Block – ein Selektor in einer Liste wird von "
            f"_LOGO_BLOCK_RE nicht erfasst (Sprint 68/79)."
        )
    for _prefix, body, _suffix in blocks:
        bounds = _LOGO_BOUND_RE.findall(body)
        if not bounds:
            violations.append(
                f"bdo_light.qss: der '{LOGO_SELECTOR}'-Block enthält keine min/max-"
                f"width/height in px – _LOGO_BOUND_RE skaliert dann nichts, das Logo "
                f"bliebe bei jeder UI-Größe gleich groß (Sprint 68/79)."
            )
    return violations


# ---------------------------------------------------------------------------
# Zusagen des Inline-Stylings (§3.2)
# ---------------------------------------------------------------------------


def check_sources_are_not_vacuous(sources: dict[str, str]) -> list[str]:
    """Anti-Vakuum für die Quelltext-Prüfungen: die Menge ist überhaupt gefüllt.

    Eine Obergrenze (`<= 53`) ist über einer leeren Dateimenge mühelos erfüllt –
    dieselbe Klasse Lücke, die der Testmengen-Wächter für die Tests schließt.
    """
    if len(sources) >= MIN_UI_SOURCE_FILES:
        return []
    return [
        f"Nur {len(sources)} Python-Datei(en) eingelesen, erwartet mindestens "
        f"{MIN_UI_SOURCE_FILES} – über einer leeren Menge sind die Obergrenzen des "
        f"Styling-Vertrags trivial erfüllt (Sprint 79)."
    ]


def check_inline_font_sizes_are_scaled(sources: dict[str, str]) -> list[str]:
    """Sprint 68/79: jede Inline-`font-size:` in `src/` geht durch `scaled_px(`.

    Das Inline-Styling ist der größere Teil des Vertrags: 52 `setStyleSheet`-
    Aufrufe in 16 Dateien gegenüber einer QSS-Datei. Eine feste Zahl in einem
    f-String (`font-size: 11px`) ist kein Syntaxfehler und keine Warnung – das
    Element ignoriert die UI-Größe ab dann einfach, und zwar nur für die
    Anwender, die „groß" oder „klein" gewählt haben.

    `_scaling.py` ist ausgenommen: das `font-size:` dort ist das Suchmuster.
    """
    violations = []
    found = 0
    for path, content in sorted(sources.items()):
        if Path(path).name == SCALING_MODULE:
            continue
        for line, value in font_size_declarations(content):
            found += 1
            if "scaled_px(" in value:
                continue
            violations.append(
                f"{path} Zeile {line}: font-size ist {value!r} und geht nicht durch "
                f"scaled_px(...) – dieses Element ignoriert die Einstellung UI-Größe "
                f"still (Sprint 68/79)."
            )
    if found == 0:
        violations.append(
            "Keine einzige Inline-font-size gefunden – über einer leeren Menge ist die "
            "Zusage trivial erfüllt; wenn das Inline-Styling wirklich verschwunden ist, "
            "gehört diese Prüfung entfernt statt grün gelassen (Sprint 79)."
        )
    return violations


def check_hex_literals_do_not_grow(sources: dict[str, str]) -> list[str]:
    """Sprint 79: die Zahl roher Hex-Literale in `ui/**/*.py` steigt nicht.

    Ein Ratchet NACH UNTEN, gespiegelt zum Testmengen-Wächter: der Wert darf
    sinken, nie steigen. Sprint 79 hat bei 53 festgehalten, dass es nicht mehr
    wird; Sprint 80 hat die 33 Literale mit vorhandener Konstante ersetzt und
    steht bei 17.

    Zusätzlich je bekannter Farbe eine eigene Grenze – seit Sprint 80 durchweg 0:
    ein Anstieg bei einer Farbe wäre in der Gesamtzahl sonst unsichtbar
    (19 → 20 bei gleichzeitigem 7 → 6).
    """
    violations = []
    total = sum(count_hex_literals(content) for content in sources.values())
    if total > HEX_LITERAL_CEILING:
        violations.append(
            f"{total} rohe Hex-Literale in ui/**/*.py, erlaubt sind höchstens "
            f"{HEX_LITERAL_CEILING} – eine neue Farbe direkt im Code statt über eine "
            f"Konstante in config.py. Der Wert wird NICHT angehoben, um diesen Lauf "
            f"grün zu machen; er darf nur sinken (Sprint 79)."
        )

    histogram = hex_literal_histogram(sources)
    for color, ceiling in KNOWN_COLOR_CEILINGS.items():
        actual = histogram.get(color.upper(), 0)
        if actual > ceiling:
            violations.append(
                f"{color} kommt {actual}× roh in ui/**/*.py vor, erlaubt sind höchstens "
                f"{ceiling} – für genau diese Farbe gibt es bereits eine Konstante in "
                f"config.py (Sprint 79)."
            )
    return violations


def check_font_sizes_are_derived_not_pinned(sources: dict[str, str]) -> list[str]:
    """Sprint 80: eine Schriftgröße wird abgeleitet, nie in der falschen Einheit gepinnt.

    Qt speichert eine Größe ENTWEDER in Punkt ODER in Pixel; die jeweils andere
    Abfrage liefert `-1`. `bdo_light.qss` deklariert `font-size: <n>px`, also ist
    auf jeder gestylten Widget-Schrift `pointSize() == -1` – und
    `setPointSize(pointSize() + 2)` ergibt eine 1-Punkt-Schrift. Der Text
    verschwindet, ohne Fehlermeldung, bei JEDEM Skalierungsfaktor, auch bei 1,0.

    Genau das stand von Sprint 1 bis 79 unbemerkt in der Datentabelle: der
    Empty-State-Hinweis rendert gemessene 21 Tintenpixel statt lesbarem Text, an
    allen drei UI-Größen gleich. Kein Test hat es gesehen, weil im ganzen Repo
    keiner eine Schrift konstruiert oder prüft.

    Drei Wege, dieselbe Größe zu pinnen – alle drei werden gemeldet:

    1. Arithmetik auf `pointSize()`/`pixelSize()` – der gemessene Fall.
    2. Ein Größen-Setter außerhalb von `_fonts.py`.
    3. `QFont("Helvetica", 9)` – Größe über den Konstruktor.

    Die drei Stellen, die Sprint 79 als Verstoß gemeldet hat
    (`import_options_dialog.py`, `sidebar.py`), sind BEWUSST nicht erfasst: ein
    parameterloses `QFont()` trägt eine leere resolve-Maske und überschreibt
    nichts – gemessen an `QFont().resolve(base)`, das die Basisgröße behält.
    Eine Zusage „kein `QFont()`" hätte dort zwei Falsch-Positive und den echten
    Fall verfehlt.
    """
    violations = []
    for path, content in sorted(sources.items()):
        name = Path(path).name
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            # Fail loud, nicht fail open: eine Datei, die nicht parst, wäre sonst
            # still von der Zusage ausgenommen.
            violations.append(
                f"{path}: nicht parsebar ({exc.msg}) – die Zusage kann hier nicht gelten."
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and name != FONTS_MODULE:
                for side in (node.left, node.right):
                    if (
                        isinstance(side, ast.Call)
                        and isinstance(side.func, ast.Attribute)
                        and side.func.attr in _FONT_SIZE_GETTERS
                    ):
                        violations.append(
                            f"{path} Zeile {node.lineno}: Arithmetik auf "
                            f"{side.func.attr}() – liefert -1, sobald die Größe in der "
                            f"anderen Einheit gesetzt ist (bei uns immer px aus der QSS). "
                            f"Über `_fonts.relative_font` ableiten (Sprint 80)."
                        )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _FONT_SIZE_SETTERS
                and name != FONTS_MODULE
            ):
                violations.append(
                    f"{path} Zeile {node.lineno}: {node.func.attr}() außerhalb von "
                    f"{FONTS_MODULE} – Schriftgrößen werden dort abgeleitet, damit die "
                    f"Einheit an einer Stelle richtig ist (Sprint 80)."
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "QFont"
                and len(node.args) >= 2
            ):
                violations.append(
                    f"{path} Zeile {node.lineno}: QFont(...) mit Größe im Konstruktor – "
                    f"pinnt die Größe absolut und ignoriert die UI-Größe (Sprint 80)."
                )
    return violations


# ---------------------------------------------------------------------------
# Registry – damit keine Zusage versehentlich ungenutzt bleibt
# ---------------------------------------------------------------------------

#: Zusagen über dem Inhalt von `bdo_light.qss`.
QSS_CHECKS: Final[tuple[QssCheck, ...]] = (
    check_stylesheet_is_not_vacuous,
    check_font_sizes_are_integer_px,
    check_blocks_are_flat,
    check_logo_block_is_scalable,
)

#: Zusagen über einem `{Pfad: Inhalt}`-Mapping von Python-Quelltexten.
#:
#: Die beiden Mengen greifen verschieden weit: die Hex-Obergrenze gilt für
#: `ui/**/*.py`, die `scaled_px`-Zusage für das ganze Paket. Welche Menge eine
#: Prüfung braucht, steht in `SOURCE_CHECK_SCOPE` – die Registry selbst bleibt
#: eine flache Liste, damit der Meta-Test keine Zusage übersehen kann.
SOURCE_CHECKS: Final[tuple[SourceCheck, ...]] = (
    check_sources_are_not_vacuous,
    check_inline_font_sizes_are_scaled,
    check_hex_literals_do_not_grow,
    check_font_sizes_are_derived_not_pinned,
)

#: `True` = die Prüfung braucht das ganze Paket, `False` = nur `ui/`.
SOURCE_CHECK_NEEDS_PACKAGE: Final[dict[str, bool]] = {
    check_sources_are_not_vacuous.__name__: False,
    check_inline_font_sizes_are_scaled.__name__: True,
    check_hex_literals_do_not_grow.__name__: False,
    # Paket-Scope: eine Schrift kann auch außerhalb von `ui/` gebaut werden, und
    # genau dort schaut niemand hin. Dieselbe Begründung wie bei `scaled_px`.
    check_font_sizes_are_derived_not_pinned.__name__: True,
}


def run_qss_checks(qss: str) -> list[str]:
    """Alle QSS-Zusagen; leere Liste = alle gehalten."""
    violations: list[str] = []
    for check in QSS_CHECKS:
        violations.extend(check(qss))
    return violations


def run_source_checks(ui: dict[str, str], package: dict[str, str]) -> list[str]:
    """Alle Quelltext-Zusagen, jede auf der Menge, für die sie gilt."""
    violations: list[str] = []
    for check in SOURCE_CHECKS:
        scope = package if SOURCE_CHECK_NEEDS_PACKAGE[check.__name__] else ui
        violations.extend(check(scope))
    return violations


def registered_checks() -> tuple[QssCheck | SourceCheck, ...]:
    """Alle registrierten Prüfungen – Grundlage des Meta-Tests."""
    return (*QSS_CHECKS, *SOURCE_CHECKS)
