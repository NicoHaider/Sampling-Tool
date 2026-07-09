-- ===========================================================================
-- Sprint 36 – Filter-Operator für Stichproben
--
-- Bestandssamples hatten implizit Gleichheits-Filter; Default 'eq' erhält das
-- historische Verhalten exakt (kein Daten-/Semantikverlust beim Backfill).
-- ===========================================================================

ALTER TABLE samples ADD COLUMN filter_operator TEXT NOT NULL DEFAULT 'eq';

INSERT INTO schema_version (version, applied_at) VALUES (3, CURRENT_TIMESTAMP);
