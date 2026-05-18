"""SelectionController – Dataset/Sample/Filter-Auswahl + AuditEvent-Doppelklick.

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Reagiert
auf UI-Interaktion (Sidebar-Klicks, Filter-Checkbox, AuditTrail-
Doppelklick) und mutiert den aktuellen Auswahl-State über die
WorkspaceSession.
"""

from __future__ import annotations

from sampling_tool.persistence.repositories import AuditRepo, SampleRepo
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import (
    AUDIT_EVENT_DISPLAY_LIMIT,
    WorkspaceSession,
)


class SelectionController:
    """Bedient Sidebar-/AuditTrail-Auswahl + Sample-Filter."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories  # nicht aktuell genutzt – Reserve für später

    # ---- Dataset --------------------------------------------------------

    def handle_dataset_selected(self, dataset_id: int) -> None:
        """Dataset aus DB laden und in der Tabelle anzeigen.

        Klick auf das aktuell schon offene Dataset ist ein No-Op (insbesondere
        bleibt ein laufendes Sample-Highlight stehen). Wechsel auf ein anderes
        Dataset versucht, das aktive Sample dort wiederzufinden – falls das
        Sample nicht zum neuen Dataset gehört, wird das Highlight geleert.

        Logik in `WorkspaceSession.select_dataset` – wird auch vom
        `WorkspaceController` nach erfolgreichem Import aufgerufen.
        """
        self.session.select_dataset(dataset_id)

    # ---- Sample ---------------------------------------------------------

    def handle_sample_selected(self, sample_id: int) -> None:
        """Sample-Zeilen in der Tabelle markieren + zur ersten scrollen.

        Wenn die Filter-Checkbox aktiv ist, wird der Filter auf das neue
        Sample umgehängt (statt zurückgesetzt).
        """
        s = self.session
        if s.db is None:
            return
        sample = SampleRepo(s.db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        s.sample = sample
        s.active_sample_id = sample.id
        if s.window.sidebar().is_filter_only_sample():
            s.window.filter_to_sample(sample)
            s.filter_active_sample_id = sample.id
            s.window.highlight_sample(sample, filtered=True)
        else:
            if s.filter_active_sample_id is not None:
                s.window.clear_sample_filter()
                s.filter_active_sample_id = None
            s.window.highlight_sample(sample)
        s.update_undo_redo_state()
        s.persist_state()

    # ---- Filter ---------------------------------------------------------

    def handle_sample_filter_toggled(self, sample_id: int) -> None:
        """Doppelklick: Filter auf Sample-Zeilen ein/aus."""
        s = self.session
        if s.db is None:
            return

        if s.filter_active_sample_id == sample_id:
            s.window.clear_sample_filter()
            s.filter_active_sample_id = None
            s.window.set_filter_only_sample(False)
            if s.sample is not None:
                s.window.set_active_sample_label(s.sample, filtered=False)
            s.persist_state()
            return

        sample = SampleRepo(s.db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        s.sample = sample
        s.active_sample_id = sample.id
        s.window.highlight_sample(sample, filtered=True)
        s.window.filter_to_sample(sample)
        s.filter_active_sample_id = sample_id
        s.window.set_filter_only_sample(True)
        s.persist_state()

    def handle_filter_only_sample_toggled(self, active: bool) -> None:
        """Sidebar-Checkbox – Filter auf aktuelles Sample ein/aus.

        Funktioniert auch, wenn programmatisch (statt durch Klick) aufgerufen –
        die Checkbox wird zur Spiegelung des States synchron mitgezogen.
        """
        s = self.session
        if s.db is None:
            return
        if active:
            if s.sample is None:
                # Ohne aktives Sample wäre die Tabelle leer – Checkbox zurücksetzen.
                s.window.set_filter_only_sample(False)
                return
            s.window.filter_to_sample(s.sample)
            s.filter_active_sample_id = s.sample.id
            s.window.set_filter_only_sample(True)
            s.window.set_active_sample_label(s.sample, filtered=True)
        else:
            s.window.clear_sample_filter()
            s.filter_active_sample_id = None
            s.window.set_filter_only_sample(False)
            if s.sample is not None:
                s.window.set_active_sample_label(s.sample, filtered=False)
        s.persist_state()

    # ---- AuditTrail-Doppelklick ----------------------------------------

    def handle_audit_event_double_clicked(self, event_id: int) -> None:
        """Doppelklick auf einen AuditTrail-Event: falls Sample-Bezug → markieren."""
        s = self.session
        if not s.has_engagement():
            return
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        events = AuditRepo(s.db.connect()).list_for_engagement(
            s.engagement.id, limit=AUDIT_EVENT_DISPLAY_LIMIT
        )
        event = next((e for e in events if e.id == event_id), None)
        if event is None or event.sample_id is None:
            return
        self.handle_sample_selected(event.sample_id)
