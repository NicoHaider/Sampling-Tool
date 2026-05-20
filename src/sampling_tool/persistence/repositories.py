"""Backward-Compat-Fassade: re-exportiert die Repos aus ihren Einzelmodulen (Sprint 19 / F-007)."""

from __future__ import annotations

from sampling_tool.persistence._json import (
    _decode_value,
    _encode_value,
    _json_dumps,
    _json_loads,
    _json_or_none,
    _json_or_none_load,
    _values_from_json,
    _values_to_json,
)
from sampling_tool.persistence.audit_repo import AuditRepo
from sampling_tool.persistence.dataset_repo import DatasetRepo
from sampling_tool.persistence.engagement_repo import EngagementRepo
from sampling_tool.persistence.engagement_state_repo import (
    EngagementState,
    EngagementStateRepo,
)
from sampling_tool.persistence.sample_repo import SampleRepo
from sampling_tool.persistence.undo_repo import UndoRepo

__all__ = [
    "AuditRepo",
    "DatasetRepo",
    "EngagementRepo",
    "EngagementState",
    "EngagementStateRepo",
    "SampleRepo",
    "UndoRepo",
    # JSON-Helfer für Tests/Tooling, die sie heute aus diesem Modul ziehen:
    "_decode_value",
    "_encode_value",
    "_json_dumps",
    "_json_loads",
    "_json_or_none",
    "_json_or_none_load",
    "_values_from_json",
    "_values_to_json",
]
