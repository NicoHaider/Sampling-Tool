"""Globale pytest-Fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)


@pytest.fixture
def db() -> Iterator[Database]:
    """Frische, migrierte In-Memory-Datenbank pro Test."""
    database = Database(Path(":memory:"))
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def engagement_id(db: Database) -> int:
    """Legt ein Default-Engagement an und gibt dessen DB-id zurück."""
    repo = EngagementRepo(db.connect())
    eng = repo.get_or_create(
        Engagement(
            auditor_name="Anna Auditorin",
            client_name="ACME GmbH",
            auditor_position="Senior Auditor",
            audit_type="ISAE 3402 Typ II",
        )
    )
    assert eng.id is not None
    return eng.id


@pytest.fixture
def sample_id(db: Database, engagement_id: int) -> int:
    """Persistiert ein Dummy-Dataset + Stichprobe und liefert die `samples.id`.

    Wird von Audit- und Undo-Tests genutzt, deren FKs auf `samples(id)` greifen.
    """
    ds = DatasetRepo(db.connect()).create(
        Dataset(
            name="dummy",
            columns=("a",),
            rows=(DatasetRow(row_id=1, values={"a": 1}),),
            engagement_id=engagement_id,
        )
    )
    assert ds.id is not None
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1)
    result = SampleResult(config=cfg, selected_row_ids=(1,), population_size=1)
    return SampleRepo(db.connect()).create_from_result(result, ds.id, "test")
