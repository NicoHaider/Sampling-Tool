-- ===========================================================================
-- Sprint 94 – Index auf (dataset_id, row_index)
--
-- Bisher gab es nur `idx_dataset_rows_dataset(dataset_id)`. Jede Abfrage nach
-- `row_index` (Tabelle nachladen, Zeilen per ID, Ziehung über alle IDs) las
-- deshalb alle Zeilen des Datensatzes und sortierte sie in einem temporären
-- B-Baum. Der neue Index ändert nur, WIE SQLite sucht, nicht WAS es liefert.
--
-- Der alte Einspalten-Index ist ein Präfix des neuen und entfällt, damit der
-- Import nicht zwei Indizes pflegt; `ON DELETE CASCADE` von `datasets` nutzt
-- das Präfix `dataset_id` weiter. `IF EXISTS`, weil ein externer SQLite-Editor
-- ihn entfernt haben kann – ohne würde die Migration zurückgerollt und das
-- Projekt ließe sich nicht mehr öffnen.
--
-- Bewusst kein UNIQUE (die Eindeutigkeit von `row_index` je Datensatz ist
-- nicht erzwungen, eine Bestandsdatei könnte daran scheitern) und kein
-- ANALYZE (der Planer nutzt den Index auch ohne `sqlite_stat1`).
-- ===========================================================================

CREATE INDEX idx_dataset_rows_dataset_row ON dataset_rows(dataset_id, row_index);
DROP INDEX IF EXISTS idx_dataset_rows_dataset;

INSERT INTO schema_version (version, applied_at) VALUES (8, CURRENT_TIMESTAMP);
