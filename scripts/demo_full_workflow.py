"""End-to-End-Demo: Engagement → Excel-Import → Sampling → Export → PDF.

Aufruf:
    python scripts/demo_full_workflow.py

Alle Artefakte landen unter `./demo_output/`:
    - engagement.db          – frische SQLite mit Sprint-2-Schema
    - source_data.xlsx       – generierte Quelldatei (200 Buchungssätze)
    - simple_sample.xlsx     – Stichprobe via SimpleSampler (25 Zeilen)
    - stratified_sample.xlsx – Stichprobe stratifiziert nach Land (15 Zeilen)
    - audit_trail.pdf        – PDF-Report aller Audit-Events

Das Skript dient gleichzeitig als manueller Smoke-Test für den
gesamten Sprint-3-Datenpfad und als ausführbare Architektur-Doku.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.core.models import (
    Engagement,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.sampling import create_sampler
from sampling_tool.io import AuditTrailPDF, ExcelExporter, ExcelImporter
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)

DEMO_DIR = Path("demo_output")


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def make_source_xlsx(path: Path, rows: int = 200) -> None:
    """Generiert eine plausible Buchungssatz-Datei für die Demo."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Buchungen"
    ws.append(["BuchungsID", "Datum", "Betrag", "Land", "Konto"])
    countries = ["AUT", "DEU", "CHE", "ITA", "FRA"]
    for i in range(1, rows + 1):
        ws.append(
            [
                f"B{i:05d}",
                datetime(2026, 1 + (i % 12), 1 + (i % 27)),
                100.0 + (i * 7.13) % 9000,
                countries[i % len(countries)],
                f"4{(i % 999):03d}",
            ]
        )
    wb.save(path)


def main() -> None:
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir()

    step(1, "Frische SQLite-Datenbank anlegen + migrieren")
    db_path = DEMO_DIR / "engagement.db"
    db = Database(db_path)
    db.migrate()
    print(f"    → {db_path} (Schema-Version {db.schema_version()})")

    step(2, "Engagement erstellen")
    engagement_repo = EngagementRepo(db.connect())
    engagement = engagement_repo.get_or_create(
        Engagement(
            auditor_name="Anna Auditorin",
            auditor_position="Senior Auditor",
            client_name="ACME GmbH",
            audit_type="ISAE 3402 Typ II",
        )
    )
    assert engagement.id is not None
    audit_logger = AuditLogger(
        AuditRepo(db.connect()),
        user_name="anna",
        engagement_id=engagement.id,
    )
    print(f"    → Engagement #{engagement.id} für {engagement.client_name}")

    step(3, "Quelldatei (Excel) generieren und importieren")
    source_xlsx = DEMO_DIR / "source_data.xlsx"
    make_source_xlsx(source_xlsx, rows=200)

    importer = ExcelImporter()
    result = importer.import_file(source_xlsx)
    # Importer kennt das Engagement nicht – wir setzen es vor dem Persistieren.
    dataset = replace(result.dataset, engagement_id=engagement.id)
    dataset = DatasetRepo(db.connect()).create(dataset)
    audit_logger.log_import(dataset)
    print(
        f"    → {len(dataset.rows)} Zeilen, "
        f"{len(dataset.columns)} Spalten, "
        f"{result.skipped_rows} übersprungen"
    )

    step(4, "Simple-Sampling (25 von 200) ziehen + persistieren")
    simple_cfg = SampleConfig(
        method=SamplingMethod.SIMPLE,
        size=25,
        seed=42,
        description="Demo: 25 zufällige Buchungen",
    )
    simple_result = create_sampler(simple_cfg).sample(dataset)
    assert dataset.id is not None
    simple_id = SampleRepo(db.connect()).create_from_result(simple_result, dataset.id, "anna")
    audit_logger.log_sampling(simple_result, sample_id=simple_id)
    print(f"    → Sample #{simple_id}, gezogen: {simple_result.actual_size} Zeilen")

    step(5, "Stratified-Sampling (15 Zeilen, geschichtet nach Land)")
    strat_cfg = SampleConfig(
        method=SamplingMethod.STRATIFIED,
        size=15,
        seed=99,
        stratum_field="Land",
        stratify_mode=StratifyMode.PROPORTIONAL,
        description="Demo: 15 Buchungen, proportional pro Land",
    )
    strat_result = create_sampler(strat_cfg).sample(dataset)
    strat_id = SampleRepo(db.connect()).create_from_result(strat_result, dataset.id, "anna")
    audit_logger.log_sampling(strat_result, sample_id=strat_id)
    print(f"    → Sample #{strat_id}, gezogen: {strat_result.actual_size} Zeilen")

    step(6, "Beide Samples nach Excel exportieren")
    exporter = ExcelExporter()
    out_simple = exporter.export_sample(
        sample=simple_result,
        dataset=dataset,
        columns=["BuchungsID", "Datum", "Betrag", "Land"],
        output_dir=DEMO_DIR,
        custom_name="DemoSimple",
        custom_id="001",
        engagement=engagement,
    )
    audit_logger.log_export(simple_id, out_simple, simple_result.actual_size)
    print(f"    → {out_simple.name}")

    out_strat = exporter.export_sample(
        sample=strat_result,
        dataset=dataset,
        columns=["BuchungsID", "Land", "Konto", "Betrag"],
        output_dir=DEMO_DIR,
        custom_name="DemoStratified",
        custom_id="002",
        engagement=engagement,
    )
    audit_logger.log_export(strat_id, out_strat, strat_result.actual_size)
    print(f"    → {out_strat.name}")

    step(7, "AuditTrail-PDF generieren")
    events = AuditRepo(db.connect()).list_for_engagement(engagement.id, limit=200)
    pdf_path = AuditTrailPDF().render(
        engagement=engagement,
        events=events,
        output_path=DEMO_DIR / "audit_trail.pdf",
    )
    print(f"    → {pdf_path.name} ({len(events)} Events)")

    step(8, "Demo abgeschlossen")
    print(f"    → Alle Artefakte unter: {DEMO_DIR.resolve()}")
    db.close()


if __name__ == "__main__":
    main()
