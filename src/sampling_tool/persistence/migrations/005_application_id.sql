-- ===========================================================================
-- Sprint 41 – Application-ID für Preflight-Erkennung (S1.4 / S-002)
--
-- PRAGMA application_id stempelt neue UND migrierende Bestands-DBs, damit
-- ein künftiger read-only Preflight beim Öffnen per application_id erkennen
-- kann, dass es sich um eine Sampling-Tool-DB handelt, ohne sie anzufassen.
-- Bestands-DBs ohne diese Migration bleiben über die Schema-/Trigger-
-- Signatur erkennbar (Fallback).
-- ===========================================================================

PRAGMA application_id = 0x42444F53;

INSERT INTO schema_version (version, applied_at) VALUES (5, CURRENT_TIMESTAMP);
