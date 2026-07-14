# BDO Audit Sampling Tool – Admin-Handbuch

Dieses Dokument richtet sich an IT-Administratoren und Audit-Manager,
die das Tool betreuen, ausrollen oder ein altes Engagement
wiederherstellen müssen.

## Datenablage

Standardmäßig liegt alles unter:

```
~/Documents/BDO Audit Sampling/
└── <MandantSanitized>/
    ├── <MandantSanitized>.db        # Hauptdatenbank (SQLite WAL)
    ├── archiv/                      # Auto-Snapshots beim Öffnen
    │   └── <stem>_YYYY-MM-DD_HH-MM-SS-ffffff_<Auditor>[~<counter>].db
    └── exports/                     # generierte Reports (xlsx/pdf/html)
```

Zusätzlich legt die App folgende Daten ab:

- **`recent.json`** unter `platformdirs.user_data_dir('AuditSamplingTool', 'BDO')`:
  Liste der zuletzt geöffneten Engagements (für Welcome-Screen).
- **`QSettings`** unter Organisation „BDO", App „Audit Sampling Tool":
  Layout-Persistenz, User-Settings (Default-Auditor, Engagement-Ordner,
  Report-Defaults, Log-Level). Auf macOS Plist-Datei in
  `~/Library/Preferences/`, auf Windows Registry unter `HKCU\Software\BDO\
  Audit Sampling Tool`.

## Backup-Strategie

Es reicht, den Engagement-Ordner vollständig zu sichern. Empfohlene
Frequenz: täglich (Volumen-Backup), wöchentlich (Cold-Storage).

Eine live verwendete `.db-wal` kann bereits committete Daten enthalten. Sie
darf deshalb nicht verworfen werden, bevor die App sauber geschlossen oder
über die SQLite-Backup-API ein konsistenter Snapshot erstellt wurde. Die
`.db-shm` enthält Koordinationszustand für SQLite. Nach dem sauberen Schließen
der App müssen die Sidecar-Dateien nicht separat gesichert werden.

## Snapshot-System

Beim Öffnen einer Engagement-`.db` legt der `EngagementVersionManager`
über die SQLite-Backup-API automatisch eine einzelne, konsistente
SQLite-`.db` im `archiv/`-Unterordner an (Compliance-Pfad für den
ISAE-3402-Versionsnachweis). Sie enthält auch alle committeten Daten aus
einem vorhandenen WAL; die `-wal`-/`-shm`-Sidecars selbst werden nicht
kopiert. Snapshots erhalten nach dem Erstellen bestmöglich das Read-Only-Flag
(`chmod 0o444`), damit sie nicht versehentlich überschrieben werden – falls
das Dateisystem dies unterstützt, mappt Windows das auf das Read-Only-Attribut.

Dateiname-Schema:

```
<stem>_<YYYY-MM-DD>_<HH-MM-SS-ffffff>_<AuditorSanitized>[~<counter>].db
```

Der Zeitanteil enthält Mikrosekunden. Falls der reservierte Zielname dennoch
bereits existiert, steht ein Zähler ab `2` mit dem Marker `~` am Ende des
Basenamens, zum Beispiel `<stem>_2026-05-11_10-30-15-123456_Anna~2.db`.
Datum und Zeit folgen unmittelbar auf den exakten DB-Stem; dadurch bleiben
Snapshots von beispielsweise `ACME.db` und `ACME_2.db` im selben Archiv
eindeutig zuordenbar. Der Marker `~` kommt im sanitisierten Auditor-Token
nicht vor, sodass auch Auditor-Namen mit abschließenden Ziffern oder
Unterstrichen eindeutig bleiben. Alte Namen mit sekundengenauem Zeitanteil
werden weiterhin erkannt.

## Update-Vorgehen

1. Den aktiven Engagement-Ordner sichern.
2. Neue Version klonen oder ZIP entpacken.
3. Im Repo-Verzeichnis `pip install -e .[dev]` ausführen.
4. App neu starten – Migrations laufen automatisch.

Das Migrations-System nutzt die `schema_version`-Tabelle und führt nur
ausstehende `persistence/migrations/NNN_*.sql`-Files aus. Rückwärts-
Migrations gibt es bewusst nicht.

## Wie Briefpapier ausgetauscht wird

Drei Optionen, in Prioritäts-Reihenfolge:

1. **Per Settings-Dialog** (empfohlen): User wählt eine eigene Datei und
   speichert. Pfad landet im `QSettings` als `custom_briefpapier_path`.
2. **User-Override im Filesystem**: BDO-Briefpapier unter
   `~/Documents/BDO Audit Sampling/briefpapier/bdo_letterhead.{png,jpg,jpeg,pdf}`
   ablegen. Wird automatisch erkannt.
3. **Paket-Default ersetzen**: die mitgelieferte Datei
   `src/sampling_tool/resources/briefpapier/bdo_placeholder.pdf` direkt
   austauschen. Sinnvoll für Roll-Out an alle Auditoren.

Unterstützte Formate: PNG, JPG/JPEG, PDF (PDF nur einseitig; mehrseitige
PDFs werden nicht überlagert).

## Altes Engagement wiederherstellen

Wenn ein Engagement versehentlich verändert wurde:

1. App vollständig schließen, damit keine Connection die Ziel-DB oder ein
   Live-WAL verwendet. Ein Live-WAL kann committete Daten enthalten und darf
   nicht manuell verworfen werden.
2. Im `archiv/`-Ordner den gewünschten Snapshot identifizieren
   (Dateiname enthält Datum + Auditor).
3. Read-Only-Flag entfernen (`chmod 644` bzw. Rechtsklick →
   „Eigenschaften" auf Windows).
4. Datei umbenennen zu `<MandantSanitized>.db` und in den Engagement-
   Ordner zurückkopieren.
5. App starten und Engagement öffnen.

Alternativ (programmatisch) über
`EngagementVersionManager.restore_from_snapshot()`. Auch dafür muss die aktive
Connection vorher geschlossen sein; der Helper entfernt vor dem Kopieren
stale `-wal`-/`-shm`-Sidecars am Ziel.

## Log-Konfiguration

Per Default loggt die App auf STDOUT mit Level `INFO`. Über den
Settings-Dialog → Erweitert lässt sich das Level auf `DEBUG` umschalten;
gilt erst nach App-Neustart.

Bei Fehler-Reports relevant: `platform.system()`, `platform.release()`
und `__version__` werden vom Bug-Report-Dialog automatisch mitgeschickt
(Checkbox „App-Version und OS mitschicken").
