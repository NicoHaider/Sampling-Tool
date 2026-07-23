# ADR 0003 – Versionierte, atomare SQLite-Migrationen

- **Status:** Angenommen (Sprint 2), atomar seit Sprint 45 / A-002
- **Betrifft:** `persistence/database.py` (`migrate`, `savepoint`),
  `persistence/migrations/NNN_*.sql`

## Kontext

Jedes Projekt ist eine eigenständige SQLite-Datei, die über viele Tool-Versionen
hinweg geöffnet wird. Bestandsdateien müssen zuverlässig auf das aktuelle Schema
gehoben werden, ohne Daten zu gefährden – auch wenn eine Migration mittendrin
fehlschlägt. Zugleich soll der Migrations-Runner **nicht** versehentlich gegen
eine beliebige (fremde) SQLite-Datei laufen.

## Entscheidung

1. **Nummerierte SQL-Dateien als SSOT.** Migrationen liegen als
   `migrations/NNN_*.sql` vor (`001_initial.sql` = komplettes Sprint-2-Schema:
   Tabellen, FKs, Indizes, Append-only-Trigger). Der Runner liest die Tabelle
   `schema_version` und führt jede Datei aus, deren Version höher ist als die
   höchste eingetragene.
2. **Lücken-/Duplikat-Erkennung.** `migrate()` bricht mit `MigrationError` ab,
   wenn `schema_version` doppelte Versionen oder Lücken enthält oder die
   Migrations-Dateien selbst eine Lücke aufweisen – kein stilles Teil-Upgrade.
3. **Atomar pro Migration.** DDL und der zugehörige `schema_version`-Eintrag
   committen **gemeinsam**: Der `schema_version`-INSERT wird in den Skript-Text
   der Migration gewrappt und per `executescript` ausgeführt. Schlägt eine
   Migration fehl, wird **nur sie** zurückgerollt; bereits gehobene Versionen
   bleiben bestehen.
4. **`executescript`-Hazard bewusst behandelt.** `executescript` committet eine
   ambient offene Transaktion **implizit** vor seinem eigenen Skript. Deshalb
   nutzt nur der Migrations-Runner dieses Muster (mit gewrapptem Versions-INSERT);
   andere atomare DDL-Pfade (z. B. die Trigger-Wiederherstellung aus
   [ADR 0002](0002-anwendungsseitig-append-only-audit-trail.md)) laufen über den
   `savepoint()`-Helper, **nicht** über handgerolltes `BEGIN`/`executescript`.
5. **Tool-Identität via `application_id`.** `PRAGMA application_id = 0x42444F53`
   („BDOS") stempelt neue und migrierende Bestands-DBs (Migration
   `005_application_id.sql`, Sprint 41 / S-002), damit der read-only Preflight
   beim Öffnen eine Sampling-Tool-DB erkennt, ohne sie anzufassen. Eine DB aus
   einer **neueren** Tool-Version wird bewusst abgelehnt statt mit altem Schema
   geöffnet.
6. **Verbindungs-PRAGMAs.** `connect()` setzt `journal_mode=WAL`,
   `foreign_keys=ON`, `synchronous=NORMAL`; Autocommit (`isolation_level=None`),
   Transaktionen explizit über `session()` und `savepoint()`.

## Migrations-Stand

| Version | Datei | Sprint | Inhalt |
|--------:|-------|-------:|--------|
| 001 | `001_initial.sql` | 2 | Basis-Schema: 8 Tabellen, FKs, Indizes, Append-only-Trigger |
| 002 | `002_engagement_state.sql` | 8.2 | `engagement_state` (aktives Dataset/Sample + Filter-Status pro Engagement) |
| 003 | `003_filter_operator.sql` | 36 | `filter_operator TEXT NOT NULL DEFAULT 'eq'` (Backfill = altes Gleichheits-Verhalten) |
| 004 | `004_algorithm_version.sql` | 39 | `algorithm_version` pro Sample (Backfill `bdo-v1`, siehe [ADR 0001](0001-versionsfester-rng-vertrag.md)) |
| 005 | `005_application_id.sql` | 41 | `PRAGMA application_id`-Stempel für den Preflight |

## Konsequenzen

- Neue Schema-Änderungen als **nächste** nummerierte Datei anlegen; nie eine
  bestehende Migration nachträglich editieren (Bestandsdateien haben sie bereits
  angewandt). Backfills so wählen, dass das alte Verhalten byte-identisch erhalten
  bleibt (vgl. `003`/`004`).
- Ein Schema-Change ist eine bewusste, testpflichtige Entscheidung – nicht das
  Nebenprodukt eines Features (vgl. die vielen „kein Schema-Change"-Anmerkungen im
  [CHANGELOG](../../CHANGELOG.md), wo Anzeige-Metadaten stattdessen app-weit in
  `QSettings` liegen).
