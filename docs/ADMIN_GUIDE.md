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
    │   └── <stem>_YYYY-MM-DD_HH-MM-SS_<Auditor>.db
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

`.db-wal` und `.db-shm` sind nur temporäre SQLite-Hilfsdateien und
müssen **nicht** gesichert werden, solange die App geschlossen ist.

## Snapshot-System

Beim Öffnen einer Engagement-`.db` legt der `EngagementVersionManager`
automatisch eine Kopie im `archiv/`-Unterordner an (Compliance-Pfad
für ISAE-3402-Versionsnachweis). Snapshots erhalten nach dem Erstellen
das Read-Only-Flag (`chmod 0o444`), damit sie nicht versehentlich
überschrieben werden – Windows mappt das auf das Read-Only-Attribut.

Dateiname-Schema:

```
<stem>_<YYYY-MM-DD>_<HH-MM-SS>_<AuditorSanitized>.db
```

Sekundengenau, kollisionsfrei bei mehreren Snapshots pro Minute.

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

1. App schließen (damit `.db-wal`/`.db-shm` weg sind).
2. Im `archiv/`-Ordner den gewünschten Snapshot identifizieren
   (Dateiname enthält Datum + Auditor).
3. Read-Only-Flag entfernen (`chmod 644` bzw. Rechtsklick →
   „Eigenschaften" auf Windows).
4. Datei umbenennen zu `<MandantSanitized>.db` und in den Engagement-
   Ordner zurückkopieren.
5. App starten und Engagement öffnen.

Alternativ (programmatisch) über `EngagementVersionManager.restore_from_snapshot()`.

## Log-Konfiguration

Per Default loggt die App auf STDOUT mit Level `INFO`. Über den
Settings-Dialog → Erweitert lässt sich das Level auf `DEBUG` umschalten;
gilt erst nach App-Neustart.

Bei Fehler-Reports relevant: `platform.system()`, `platform.release()`
und `__version__` werden vom Bug-Report-Dialog automatisch mitgeschickt
(Checkbox „App-Version und OS mitschicken").
