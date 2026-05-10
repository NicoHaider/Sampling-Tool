-- ===========================================================================
-- Sprint 2 – Initial Schema
--
-- Eine SQLite-Datei pro Engagement (Mandanten-Trennung, DSGVO, Archivierung).
-- Append-only Audit-Log via Triggern – UPDATE/DELETE auf audit_events
-- werden hart blockiert.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Versionierung
-- ---------------------------------------------------------------------------
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Engagements – pro DB nur 1 Zeile, Tabelle für Erweiterbarkeit
-- ---------------------------------------------------------------------------
CREATE TABLE engagements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    auditor_name     TEXT NOT NULL,
    auditor_position TEXT NOT NULL DEFAULT '',
    client_name      TEXT NOT NULL,
    audit_type       TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Datensätze (importierte Tabellen)
-- ---------------------------------------------------------------------------
CREATE TABLE datasets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id INTEGER NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    source_file   TEXT NOT NULL DEFAULT '',
    imported_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    row_count     INTEGER NOT NULL,
    columns_json  TEXT NOT NULL
);
CREATE INDEX idx_datasets_engagement ON datasets(engagement_id);

CREATE TABLE dataset_rows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id  INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    row_index   INTEGER NOT NULL,
    values_json TEXT NOT NULL
);
CREATE INDEX idx_dataset_rows_dataset ON dataset_rows(dataset_id);

-- ---------------------------------------------------------------------------
-- Stichproben
-- ---------------------------------------------------------------------------
CREATE TABLE samples (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    method           TEXT NOT NULL,
    sample_size      INTEGER NOT NULL,
    population_size  INTEGER NOT NULL,
    seed             INTEGER NOT NULL,
    filter_field     TEXT,
    filter_value     TEXT,
    cluster_field    TEXT,
    stratum_field    TEXT,
    stratify_mode    TEXT,
    parent_sample_id INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by       TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX idx_samples_dataset ON samples(dataset_id);

CREATE TABLE sample_rows (
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    row_id    INTEGER NOT NULL,
    PRIMARY KEY (sample_id, row_id)
);

-- ---------------------------------------------------------------------------
-- Audit-Log (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE audit_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id     INTEGER NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    timestamp         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type        TEXT NOT NULL,
    user_name         TEXT NOT NULL DEFAULT 'system',
    sample_id         INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    sample_size       INTEGER,
    sample_percent    REAL,
    total_count       INTEGER,
    seed              INTEGER,
    import_file       TEXT,
    export_file       TEXT,
    details_json      TEXT,
    corrects_event_id INTEGER REFERENCES audit_events(id) ON DELETE SET NULL
);
CREATE INDEX idx_audit_events_engagement_timestamp
    ON audit_events(engagement_id, timestamp);

-- Append-only Schutz: jede UPDATE/DELETE-Operation auf audit_events
-- wird mit klarer Fehlermeldung abgebrochen.
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

-- ---------------------------------------------------------------------------
-- Undo / Redo Snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE undo_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id    INTEGER NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    stack_type       TEXT    NOT NULL CHECK (stack_type IN ('undo', 'redo')),
    position         INTEGER NOT NULL,
    sample_id        INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    visible_rows     TEXT    NOT NULL DEFAULT '[]',
    highlighted_rows TEXT    NOT NULL DEFAULT '[]',
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_undo_snapshots_engagement_stack
    ON undo_snapshots(engagement_id, stack_type, position);

-- ---------------------------------------------------------------------------
-- Versions-Marker setzen
-- ---------------------------------------------------------------------------
INSERT INTO schema_version (version, applied_at) VALUES (1, CURRENT_TIMESTAMP);
