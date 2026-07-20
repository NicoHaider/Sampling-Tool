# Installation: Audit Sampling Tool

Anleitung für Anwender (Auditoren). Die App wird als doppelklickbares Bundle
ausgeliefert – keine Python-Installation nötig.

## Download verifizieren (Pflicht vor jeder Sicherheitsabfrage-Umgehung)

Jeder Release im [Release-Bereich](https://github.com/NicoHaider/Sampling-Tool/releases)
enthält neben den ZIPs eine Datei `SHA256SUMS` mit den SHA-256-Prüfsummen der
Artefakte. **Bevor** du eine Gatekeeper- oder SmartScreen-Warnung umgehst,
prüfe, dass die heruntergeladene ZIP unverändert ist:

**macOS (Terminal):**

```bash
shasum -a 256 ~/Downloads/AuditSamplingTool-macOS.zip
```

**Windows (PowerShell):**

```powershell
Get-FileHash "$env:USERPROFILE\Downloads\AuditSamplingTool-Windows.zip" -Algorithm SHA256
```

Vergleiche den ausgegebenen Hash mit dem passenden Eintrag in `SHA256SUMS`
aus demselben Release. Stimmen die Werte überein, fahre mit der Installation
fort. Stimmen sie **nicht** überein: Datei nicht verwenden, nicht
installieren, und bei Nico Haider (nico.haider@bdo.at) melden.

## macOS

1. Lade `AuditSamplingTool-macOS.zip` aus dem
   [Release-Bereich](https://github.com/NicoHaider/Sampling-Tool/releases)
   herunter.
2. Prüfe die SHA-256-Summe der ZIP wie oben beschrieben.
3. Entpacke die ZIP. Du erhältst `Audit Sampling Tool.app`.
4. Ziehe die App nach `/Programme`.

### Erste Öffnung – wichtig

Beim ersten Doppelklick zeigt macOS möglicherweise:

> "Audit Sampling Tool" kann nicht geöffnet werden, weil es von einem
> unbekannten Entwickler stammt.

Das ist normal – die App ist (bewusst) nicht signiert (siehe FAQ unten).
Öffne sie nur, wenn du die Prüfsumme oben bereits verifiziert hast. So
öffnest du sie trotzdem:

1. **Rechtsklick** auf die App → **"Öffnen"**
2. Im erscheinenden Dialog: **"Öffnen"** klicken
3. Ab jetzt kannst du normal doppelklicken

Alternativ über *Systemeinstellungen → Datenschutz & Sicherheit → "Dennoch
öffnen"*.

### Falls die App nach dem Update weiter blockiert wird

Manchmal markiert macOS die App nach dem Download als "Quarantäne". Führe
den folgenden Schritt **nur aus, nachdem du die Prüfsumme oben erfolgreich
verifiziert hast** – `xattr -cr` entfernt Gatekeepers Quarantäne-Flag ohne
eigene Prüfung und ist kein Ersatz für die Herkunftskontrolle. Wenn die App
nach dem "Öffnen"-Trick noch immer nicht startet, im Terminal:

```bash
xattr -cr "/Applications/Audit Sampling Tool.app"
```

Dann erneut starten.

## Windows

1. Lade `AuditSamplingTool-Windows.zip` aus dem
   [Release-Bereich](https://github.com/NicoHaider/Sampling-Tool/releases)
   herunter.
2. Prüfe die SHA-256-Summe der ZIP wie oben beschrieben.
3. Entpacke die ZIP an einen geeigneten Ort, z. B.
   `C:\Programme\AuditSamplingTool\`.
4. Optional: Verknüpfung von `AuditSamplingTool.exe` auf den Desktop legen.

### Erste Öffnung – wichtig

Beim ersten Doppelklick zeigt Windows möglicherweise:

> Der Computer wurde durch Windows geschützt
> Microsoft Defender SmartScreen hat den Start einer nicht erkannten App
> verhindert.

Das ist normal – die App ist nicht signiert. Fahre nur fort, wenn du die
Prüfsumme oben bereits verifiziert hast. So öffnest du sie:

1. Auf **"Weitere Informationen"** klicken
2. Dann auf **"Trotzdem ausführen"**
3. Ab jetzt startet die App ohne Warnung

## Erste Schritte

Siehe [USER_GUIDE.md](USER_GUIDE.md) für eine Einführung in die Bedienung.

## Updates

Eine neue Version installierst du, indem du die neueste ZIP aus dem
Release-Bereich lädst, die Prüfsumme verifizierst (siehe oben) und die alte
App ersetzt. Deine Engagements (`~/Documents/BDO Audit Sampling/` bzw.
`Dokumente\BDO Audit Sampling\`) bleiben unverändert erhalten.

## FAQ

**Warum ist die App nicht signiert?**
Code-Signing-Zertifikate kosten 200–500 € pro Jahr (Apple) bzw. mehrere hundert
Euro (Windows EV). Für ein internes BDO-Tool ist das aktuell overkill. Die
SHA-256-Prüfsumme im Release ersetzt kein Code-Signing, erlaubt dir aber, die
Herkunft der Datei zu verifizieren, bevor du eine Sicherheitswarnung umgehst.
Sollte das Tool extern verteilt werden, kann Code-Signing in einem späteren
Sprint nachgerüstet werden.

**Wo werden meine Daten gespeichert?**
Standardmäßig in `~/Documents/BDO Audit Sampling/` (Mac) bzw.
`Dokumente\BDO Audit Sampling\` (Windows). Pfad ist in *Einstellungen →
Allgemein → Engagement-Verzeichnis* änderbar.

**Das Tool startet nicht / stürzt direkt ab.**
Schicke bitte einen Bug-Report via *Hilfe → Bug Report* im Tool – falls das
Tool gar nicht startet, melde dich direkt bei Nico Haider
(nico.haider@bdo.at) und schicke wenn möglich den Inhalt der
Konsole / des Terminals.

**Brauche ich Python oder Excel?**
Nein. Die App bringt alle Abhängigkeiten mit. Excel ist nur dann nötig,
wenn du die exportierten `.xlsx`-Berichte selbst öffnen willst – das Tool
schreibt sie auch ohne installiertes Excel.
