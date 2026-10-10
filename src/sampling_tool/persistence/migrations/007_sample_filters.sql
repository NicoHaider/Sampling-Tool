-- ===========================================================================
-- Sprint 92 – Mehrere Filter je Stichprobe (UND-verknüpft)
--
-- `samples.filters`: JSON-Liste aller Bedingungen
-- `[{"field": …, "operator": …, "value": …}]`, Wert wie bisher als JSON.
-- Ab hier liest die App ausschließlich diese Spalte.
--
-- Backfill aus den Altspalten: eine gefilterte Bestandsstichprobe bekommt eine
-- Ein-Element-Liste, eine ungefilterte '[]'. `filter_value` ist JSON-Text; ein
-- (theoretischer) Nicht-JSON-Wert wird als String übernommen statt die
-- Migration abzubrechen.
--
-- Die Altspalten `filter_field`/`filter_value`/`filter_operator` bleiben
-- stehen (keine destruktive Migration). Die App befüllt sie weiter, wenn genau
-- ein Filter gesetzt ist, sonst NULL bzw. 'eq'.
-- ===========================================================================

ALTER TABLE samples ADD COLUMN filters TEXT NOT NULL DEFAULT '[]';

UPDATE samples
SET filters = json_array(
    json_object(
        'field', filter_field,
        'operator', filter_operator,
        'value', CASE
            WHEN filter_value IS NULL THEN NULL
            WHEN json_valid(filter_value) THEN json(filter_value)
            ELSE filter_value
        END
    )
)
WHERE filter_field IS NOT NULL;

INSERT INTO schema_version (version, applied_at) VALUES (7, CURRENT_TIMESTAMP);
