"""F-007: repositories.py ist Re-Export-Fassade, jeder Repo lebt im eigenen Modul."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestRepositoriesBackwardCompat:
    def test_all_repos_importable_from_repositories_facade(self) -> None:
        from sampling_tool.persistence.repositories import (
            AuditRepo,
            DatasetRepo,
            EngagementRepo,
            EngagementState,
            EngagementStateRepo,
            SampleRepo,
            UndoRepo,
        )

        for cls in (
            AuditRepo,
            DatasetRepo,
            EngagementRepo,
            EngagementState,
            EngagementStateRepo,
            SampleRepo,
            UndoRepo,
        ):
            assert cls is not None

    def test_json_helpers_reexported_from_facade(self) -> None:
        from sampling_tool.persistence.repositories import (
            _decode_value,
            _encode_value,
            _json_dumps,
            _json_loads,
            _json_or_none,
            _json_or_none_load,
            _values_from_json,
            _values_to_json,
        )

        for fn in (
            _decode_value,
            _encode_value,
            _json_dumps,
            _json_loads,
            _json_or_none,
            _json_or_none_load,
            _values_from_json,
            _values_to_json,
        ):
            assert callable(fn)

    def test_each_repo_lives_in_own_module(self) -> None:
        from sampling_tool.persistence.audit_repo import AuditRepo
        from sampling_tool.persistence.dataset_repo import DatasetRepo
        from sampling_tool.persistence.engagement_repo import EngagementRepo
        from sampling_tool.persistence.engagement_state_repo import (
            EngagementState,
            EngagementStateRepo,
        )
        from sampling_tool.persistence.repositories import (
            AuditRepo as FacadeAudit,
        )
        from sampling_tool.persistence.sample_repo import SampleRepo
        from sampling_tool.persistence.undo_repo import UndoRepo

        # Fassaden-Symbol ist identisch mit dem Modul-Symbol.
        assert FacadeAudit is AuditRepo
        assert DatasetRepo.__module__ == "sampling_tool.persistence.dataset_repo"
        assert EngagementRepo.__module__ == "sampling_tool.persistence.engagement_repo"
        assert SampleRepo.__module__ == "sampling_tool.persistence.sample_repo"
        assert EngagementStateRepo.__module__ == "sampling_tool.persistence.engagement_state_repo"
        assert EngagementState.__module__ == "sampling_tool.persistence.engagement_state_repo"
        assert UndoRepo.__module__ == "sampling_tool.persistence.undo_repo"
