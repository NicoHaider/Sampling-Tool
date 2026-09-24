-- ===========================================================================
-- Sprint 83 – Nachvollziehbarkeit im Audit-Trail (Smoke-Test 24.09.2026,
-- Befunde 4 + 5)
--
-- `samples.parent_relation`: WIE eine Stichprobe aus ihrer Eltern-Stichprobe
-- abgeleitet wurde ('restrict' = nur aus aktueller Auswahl, 'supplement' =
-- Nachstichprobe ohne Dubletten). Vorher stand beides nur als
-- `parent_sample_id` da – der Unterschied war allenfalls an der
-- Populationsgröße erratbar.
--
-- `datasets.source_sheet` / `datasets.header_row`: aus welchem Blatt und ab
-- welcher Kopfzeile (1-basiert wie im Import-Dialog, 0 = keine Kopfzeile)
-- importiert wurde.
--
-- KEIN Backfill (anders als 004): Für Bestandssamples ließe sich die Ableitung
-- nur aus Populationsgröße und Überschneidung SCHÄTZEN, Blatt und Kopfzeile
-- von Bestands-Datasets sind nirgends gespeichert. 004 durfte backfillen, weil
-- der Wert dort feststand; hier stünde eine Vermutung im Audit-Trail. NULL
-- heißt „nicht erfasst (älterer Stand)" und wird genau so angezeigt.
-- ===========================================================================

ALTER TABLE samples ADD COLUMN parent_relation TEXT
    CHECK (parent_relation IN ('restrict', 'supplement'));

ALTER TABLE datasets ADD COLUMN source_sheet TEXT;

ALTER TABLE datasets ADD COLUMN header_row INTEGER;

INSERT INTO schema_version (version, applied_at) VALUES (6, CURRENT_TIMESTAMP);
