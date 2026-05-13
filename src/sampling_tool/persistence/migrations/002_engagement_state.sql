-- ===========================================================================
-- Sprint 8.2 – UI-State pro Engagement persistieren
--
-- `engagement_state` speichert pro Engagement das zuletzt aktive Dataset,
-- das zuletzt aktive Sample und den Filter-Status. Beim Öffnen des
-- Engagements stellt der MainController diesen State wieder her, damit
-- Sample-Highlight, Filter-Checkbox und Tabellenansicht zwischen Sessions
-- nicht verloren gehen.
-- Genau eine Zeile pro Engagement (engagement_id ist PRIMARY KEY).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS engagement_state (
    engagement_id     INTEGER PRIMARY KEY
                              REFERENCES engagements(id) ON DELETE CASCADE,
    active_dataset_id INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
    active_sample_id  INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    filter_active     INTEGER NOT NULL DEFAULT 1,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_version (version, applied_at) VALUES (2, CURRENT_TIMESTAMP);
