# ADR 0002 – Anwendungsseitig append-only Audit-Trail

- **Status:** Angenommen (Sprint 2), Threat-Model präzisiert + Tamper-Erkennung
  ergänzt (Sprint 52 / S2.7, S-004)
- **Betrifft:** `persistence/migrations/001_initial.sql`, `persistence/database.py`
  (`AUDIT_APPEND_ONLY_TRIGGERS`), `persistence/db_preflight.py`, `audit/logger.py`

## Kontext

Der Audit-Trail (`audit_events`) ist der ISAE-3402-Nachweis über Importe,
Ziehungen, Exporte, Undo/Redo, Resets und Korrekturen. Nachträgliches Ändern oder
Löschen von Ereignissen würde den Nachweis wertlos machen. Zugleich liegt jede
Projekt-`.db` als normale Datei im Benutzerdateisystem – ein vollständiger,
kryptografischer Manipulationsschutz (signierte Checkpoints o. Ä.) ist bewusst
**nicht** Teil dieses Tools.

## Entscheidung

1. **INSERT-only per Trigger.** `audit_events` darf ausschließlich per `INSERT`
   befüllt werden. Zwei BEFORE-Trigger (`audit_events_no_update`,
   `audit_events_no_delete`) blockieren UPDATE/DELETE hart mit
   `RAISE(ABORT, 'audit_events is append-only')` – über **jede** sqlite3-
   Connection.
2. **Korrekturen sind neue Ereignisse.** Eine fachliche Korrektur wird als neues
   Event mit `event_type='correction'` und `corrects_event_id`-FK auf das
   Original gespeichert – **kein** UPDATE/DELETE des Originals.
3. **Bewusst „anwendungsseitig append-only".** Der Schutz greift über die
   App-Trigger. Ein externer SQLite-Editor kann die Trigger entfernen/entkernen;
   das ist die anerkannte Grenze des Modells.
4. **Tamper-Erkennung + Wiederherstellung beim Öffnen (Sprint 52).** Zwei
   getrennte Akteure: Der read-only Preflight (`persistence/db_preflight.py`)
   prüft die Trigger **strukturell** (Definition, nicht nur den Namen) und meldet
   Manipulation über das Flag `audit_triggers_tampered` – er schreibt selbst
   **nie** auf die Datei. Ist das Flag gesetzt, stellt ein separater Schritt auf
   der Schreib-Connection die kanonischen Trigger
   (`database.py::AUDIT_APPEND_ONLY_TRIGGERS`) über
   `restore_audit_append_only_triggers()` wieder her (aufgerufen aus dem
   `EngagementController` beim Öffnen; Variante 1: warnen + reparieren, das Öffnen
   wird nicht blockiert). Die Wiederherstellung läuft über `savepoint()` – nicht
   über `executescript` mit eigenem `BEGIN`/`COMMIT` (siehe
   [ADR 0003](0003-db-migrationen.md)).

## Konsequenzen

- **Kein hartes Löschen** von Stichproben oder Datensätzen aus einem Projekt.
  Reset-/„aus Ansicht entfernen"-Funktionen sind reine In-Memory-/Ansichts-Resets;
  die zugrunde liegenden `audit_events`/`samples` bleiben in der DB. Eine
  identische Re-Ziehung mit gleichem Seed rekonstruiert die Stichprobe bit-genau.
- Dies ist Tamper-**Erkennung**, kein kryptografischer Manipulationsnachweis.
  Signierte Checkpoints wären dafür nötig – bewusst außerhalb des Scopes.
- `foreign_keys=ON` ist Voraussetzung: `audit_events.sample_id` ist
  `ON DELETE SET NULL`; ein Sample-Delete würde die SET-NULL-Aktion auf
  `audit_events` auslösen und am `no_update`-Trigger scheitern (`IntegrityError`).
  Das ist gewollt und stützt Punkt 1.
