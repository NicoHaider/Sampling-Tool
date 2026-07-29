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
from typing import TYPE_CHECKING, Any

from sampling_tool.core.models import Dataset, Engagement, FilterOperator, SampleResult
from sampling_tool.io.importer import ExcelImporter
from sampling_tool.ui.dialogs.duplicate_engagement_dialog import DuplicateEngagementDialog
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialog
from sampling_tool.ui.dialogs.export_excel_report_dialog import ExportExcelReportDialog
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog
from sampling_tool.ui.dialogs.id_column_dialog import IdColumnDialog
from sampling_tool.ui.dialogs.import_options_dialog import ImportOptionsDialog
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialog
from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
from sampling_tool.ui.settings_store import AppSettings, SamplingFeatures

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Factory-Typen
# ---------------------------------------------------------------------------


DialogFactory = Callable[["MainWindow", AppSettings, Engagement | None], NewEngagementDialog]
DuplicateDialogFactory = Callable[["MainWindow", Path], DuplicateEngagementDialog]
SamplingDialogFactory = Callable[
    [
        "MainWindow",
        Dataset,
        Callable[[str], Sequence[Any]] | None,
        SampleResult | None,
        SamplingFeatures,
        Callable[[str, FilterOperator, Any, bool], int] | None,
        float,
    ],
    SamplingDialog,
]
ExportDialogFactory = Callable[["MainWindow", Dataset, str, str, Path | None], ExportSampleDialog]
AuditPdfDialogFactory = Callable[
    [
        "MainWindow",
        Engagement,
        list[str],
        bool,
        Path | None,
        bool,
        bool,
        bool,
        str | None,
        str | None,
    ],
    ExportAuditPdfDialog,
]
ExcelReportDialogFactory = Callable[
    ["MainWindow", Engagement, Path | None], ExportExcelReportDialog
]
HtmlReportDialogFactory = Callable[["MainWindow", Engagement, Path | None], ExportHtmlReportDialog]
SettingsDialogFactory = Callable[["MainWindow", AppSettings], SettingsDialog]
ImportOptionsDialogFactory = Callable[[Path, ExcelImporter, "MainWindow"], ImportOptionsDialog]
# Sprint 31: optionaler Post-Import-Schritt – ID-Spalte für die Sidebar wählen.
IdColumnDialogFactory = Callable[[list[str], str | None, "MainWindow"], IdColumnDialog]


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
    import_options: ImportOptionsDialogFactory
    id_column: IdColumnDialogFactory

    @classmethod
    def defaults(cls) -> ControllerFactories:
        """Bündelt die 10 `default_*_factory`-Funktionen zu einem Bundle.

        Sprint 59 / Teil B (L-003): einziger Ort, an dem die Default-Factories
        auf die Bundle-Felder gemappt werden – `MainController.__init__`
        baut Overrides per `dataclasses.replace(cls.defaults(), **overrides)`
        statt 10 einzelner Ternaries.
        """
        return cls(
            new_engagement=default_new_engagement_factory,
            duplicate=default_duplicate_dialog_factory,
            sampling=default_sampling_factory,
            export_sample=default_export_factory,
            audit_pdf=default_audit_pdf_factory,
            excel_report=default_excel_report_factory,
            html_report=default_html_report_factory,
            settings=default_settings_factory,
            import_options=default_import_options_factory,
            id_column=default_id_column_factory,
        )


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
    distinct_values_provider: Callable[[str], Sequence[Any]] | None,
    current_sample: SampleResult | None,
    features: SamplingFeatures,
    filter_match_count_provider: Callable[[str, FilterOperator, Any, bool], int] | None = None,
    ui_scale_factor: float = 1.0,
) -> SamplingDialog:
    return SamplingDialog(
        dataset,
        distinct_values_provider,
        current_sample=current_sample,
        parent=parent,
        features=features,
        filter_match_count_provider=filter_match_count_provider,
        ui_scale_factor=ui_scale_factor,
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
    offer_date_filter: bool = False,
    default_company_key: str | None = None,
    default_location_key: str | None = None,
) -> ExportAuditPdfDialog:
    return ExportAuditPdfDialog(
        engagement=engagement,
        event_types_available=event_types_available,
        briefpapier_available=briefpapier_available,
        parent=parent,
        default_output_dir=default_dir,
        default_use_briefpapier=default_use_briefpapier,
        default_include_statistics=default_include_statistics,
        offer_date_filter=offer_date_filter,
        default_company_key=default_company_key,
        default_location_key=default_location_key,
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


def default_import_options_factory(
    path: Path, importer: ExcelImporter, parent: MainWindow
) -> ImportOptionsDialog:
    return ImportOptionsDialog(path=path, importer=importer, parent=parent)


def default_id_column_factory(
    columns: list[str], current: str | None, parent: MainWindow
) -> IdColumnDialog:
    return IdColumnDialog(columns, current=current, parent=parent)
