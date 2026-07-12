-- ===========================================================================
-- Sprint 39 – Versionsfester RNG-Vertrag (S1.2 / R-001)
--
-- Bestandssamples wurden mit exakt diesem Algorithmus gezogen (Variante A:
-- BitGenerator explizit gemacht, output-identisch) – Default 'bdo-v1' ist
-- daher ein korrekter Backfill, keine Schätzung.
-- ===========================================================================

ALTER TABLE samples ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'bdo-v1';

INSERT INTO schema_version (version, applied_at) VALUES (4, CURRENT_TIMESTAMP);
