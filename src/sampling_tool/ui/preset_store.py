"""App-weite Persistenz für Sampling-Presets (Sprint 23).

Eine einzige Verwaltungs-Stelle für `SamplingPreset`s: `list` / `save` /
`rename` / `delete`. Gespeichert wird app-weit über dasselbe `QSettings`-
Muster wie `AppSettings` (Sprint 22) – **nicht** in die Engagement-SQLite-DB,
kein Schema-Change, keine Migration. Serialisierung als JSON-String (stdlib,
über `core.presets`), abgelegt unter einem einzelnen QSettings-Key.

Die reine Domain-Logik (Modell + JSON) lebt in `core.presets`; dieser Store
ist die UI-Schicht-Brücke zu Qt-`QSettings` (analog `settings_store.py`).
"""

from __future__ import annotations

import builtins
from dataclasses import replace
from typing import Final

from sampling_tool.core.presets import (
    SamplingPreset,
    deserialize_presets,
    serialize_presets,
)
from sampling_tool.ui import settings_store

_PRESETS_KEY: Final[str] = "presets/json"


class PresetStore:
    """CRUD über die app-weit gespeicherten Sampling-Presets.

    Die Methode heißt bewusst `list()` (Sprint-23-Spec). Annotationen, die den
    eingebauten `list`-Typ meinen, nutzen `builtins.list[...]`, weil der
    Methoden-Name `list` ihn im Klassen-Scope sonst überschattet.
    """

    def list(self) -> builtins.list[SamplingPreset]:
        """Alle Presets, alphabetisch (case-insensitiv) nach Name sortiert."""
        raw = _str(settings_store.open_qsettings().value(_PRESETS_KEY, ""))
        presets = deserialize_presets(raw)
        return sorted(presets, key=lambda p: p.name.casefold())

    def names(self) -> builtins.list[str]:
        """Nur die Namen – Reihenfolge wie `list()`."""
        return [p.name for p in self.list()]

    def get(self, name: str) -> SamplingPreset | None:
        """Liefert das Preset mit exaktem Namen oder `None`."""
        return next((p for p in self.list() if p.name == name), None)

    def exists(self, name: str) -> bool:
        """True, wenn bereits ein Preset mit diesem Namen gespeichert ist."""
        return any(p.name == name for p in self.list())

    def save(self, preset: SamplingPreset) -> None:
        """Speichert ein Preset; ein vorhandenes mit gleichem Namen wird ersetzt.

        Reine Persistenz – die Überschreib-*Bestätigung* ist UI-Sache (Dialog).
        """
        presets = [p for p in self.list() if p.name != preset.name]
        presets.append(preset)
        self._write(presets)

    def rename(self, old: str, new: str) -> bool:
        """Benennt ein Preset um. Liefert `False`, wenn `old` nicht existiert.

        Ein bereits vorhandenes Preset namens `new` wird ersetzt (die
        Überschreib-Bestätigung liegt beim Aufrufer/Dialog).
        """
        presets = self.list()
        target = next((p for p in presets if p.name == old), None)
        if target is None:
            return False
        kept = [p for p in presets if p.name not in (old, new)]
        kept.append(_replace_name(target, new))
        self._write(kept)
        return True

    def delete(self, name: str) -> None:
        """Entfernt das Preset mit diesem Namen (No-Op, wenn nicht vorhanden)."""
        self._write([p for p in self.list() if p.name != name])

    # ---- intern --------------------------------------------------------

    @staticmethod
    def _write(presets: builtins.list[SamplingPreset]) -> None:
        qs = settings_store.open_qsettings()
        qs.setValue(_PRESETS_KEY, serialize_presets(presets))
        qs.sync()


def _replace_name(preset: SamplingPreset, new: str) -> SamplingPreset:
    return replace(preset, name=new)


def _str(value: object) -> str:
    return "" if value is None else str(value)
