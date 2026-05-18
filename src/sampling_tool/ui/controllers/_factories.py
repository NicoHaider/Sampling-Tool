"""Dialog-Factory-Bündel + Default-Implementierungen.

Sprint 13 / F-001: aus dem MainController-Modul herausgezogen, damit
jeder Sub-Controller sich nur die ihm relevanten Factories holen kann
ohne den vollen MainController-Kontext zu brauchen.

Die Factory-Typen bleiben strukturell `Callable[...]` – Production-Caller
und Tests können beliebige Konstruktor-Wrapper einsetzen, solange die
Signatur passt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sampling_tool.core.models import Dataset, DatasetRow, Engagement, SampleResult
from sampling_tool.ui.dialogs.duplicate_engagement_dialog import DuplicateEngagementDialog
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialog
from sampling_tool.ui.dialogs.export_excel_report_dialog import ExportExcelReportDialog
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialog
from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
from sampling_tool.ui.settings_store import AppSettings

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Factory-Typen
# ---------------------------------------------------------------------------


DialogFactory = Callable[["MainWindow", AppSettings, Engagement | None], NewEngagementDialog]
DuplicateDialogFactory = Callable[["MainWindow", Path], DuplicateEngagementDialog]
SamplingDialogFactory = Callable[
    ["MainWindow", Dataset, Sequence[DatasetRow] | None, SampleResult | None, bool],
    SamplingDialog,
]
ExportDialogFactory = Callable[["MainWindow", Dataset, str, str, Path | None], ExportSampleDialog]
AuditPdfDialogFactory = Callable[
    ["MainWindow", Engagement, list[str], bool, Path | None, bool, bool],
    ExportAuditPdfDialog,
]
ExcelReportDialogFactory = Callable[
    ["MainWindow", Engagement, Path | None], ExportExcelReportDialog
]
HtmlReportDialogFactory = Callable[["MainWindow", Engagement, Path | None], ExportHtmlReportDialog]
SettingsDialogFactory = Callable[["MainWindow", AppSettings], SettingsDialog]


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControllerFactories:
    """Frozen Bundle aller Dialog-Factories – ein Sub-Controller nimmt sich
    nur die, die er braucht. Frozen weil Factories sich zur Laufzeit nicht
    ändern.
    """

    new_engagement: DialogFactory
    duplicate: DuplicateDialogFactory
    sampling: SamplingDialogFactory
    export_sample: ExportDialogFactory
    audit_pdf: AuditPdfDialogFactory
    excel_report: ExcelReportDialogFactory
    html_report: HtmlReportDialogFactory
    settings: SettingsDialogFactory


# ---------------------------------------------------------------------------
# Default-Factories
# ---------------------------------------------------------------------------


def default_new_engagement_factory(
    parent: MainWindow,
    settings: AppSettings,
    initial_engagement: Engagement | None,
) -> NewEngagementDialog:
    return NewEngagementDialog(
        parent=parent,
        default_auditor_name=settings.default_auditor_name or None,
        engagements_dir=settings.engagements_dir,
        initial_engagement=initial_engagement,
    )


def default_duplicate_dialog_factory(
    parent: MainWindow, db_path: Path
) -> DuplicateEngagementDialog:
    return DuplicateEngagementDialog(db_path=db_path, parent=parent)


def default_sampling_factory(
    parent: MainWindow,
    dataset: Dataset,
    rows: Sequence[DatasetRow] | None,
    current_sample: SampleResult | None,
    advanced_mode: bool,
) -> SamplingDialog:
    return SamplingDialog(
        dataset,
        rows,
        current_sample=current_sample,
        parent=parent,
        advanced_mode=advanced_mode,
    )


def default_export_factory(
    parent: MainWindow,
    dataset: Dataset,
    default_name: str,
    default_id: str,
    default_dir: Path | None,
) -> ExportSampleDialog:
    return ExportSampleDialog(
        dataset,
        default_name=default_name,
        default_id=default_id,
        default_output_dir=default_dir,
        parent=parent,
    )


def default_audit_pdf_factory(
    parent: MainWindow,
    engagement: Engagement,
    event_types_available: list[str],
    briefpapier_available: bool,
    default_dir: Path | None,
    default_use_briefpapier: bool = True,
    default_include_statistics: bool = True,
) -> ExportAuditPdfDialog:
    return ExportAuditPdfDialog(
        engagement=engagement,
        event_types_available=event_types_available,
        briefpapier_available=briefpapier_available,
        parent=parent,
        default_output_dir=default_dir,
        default_use_briefpapier=default_use_briefpapier,
        default_include_statistics=default_include_statistics,
    )


def default_excel_report_factory(
    parent: MainWindow,
    engagement: Engagement,
    default_dir: Path | None,
) -> ExportExcelReportDialog:
    return ExportExcelReportDialog(engagement, parent=parent, default_output_dir=default_dir)


def default_html_report_factory(
    parent: MainWindow,
    engagement: Engagement,
    default_dir: Path | None,
) -> ExportHtmlReportDialog:
    return ExportHtmlReportDialog(engagement, parent=parent, default_output_dir=default_dir)


def default_settings_factory(parent: MainWindow, current: AppSettings) -> SettingsDialog:
    return SettingsDialog(current, parent=parent)
