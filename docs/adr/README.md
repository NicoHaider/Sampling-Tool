# Architecture Decision Records (ADRs)

Kurze, langlebige Festhaltungen der **bedeutenden** Architektur-Entscheidungen
des BDO Audit Sampling Tools. Jede ADR beschreibt Kontext, Entscheidung und
Konsequenzen einer Festlegung, die den Code über viele Sprints hinweg bindet.

Diese ADRs **destillieren bestehende** Entscheidungen aus `CLAUDE.md` und dem
Code – sie erfinden keine neuen. Die granulare Sprint-Historie steht im
[CHANGELOG](../../CHANGELOG.md); die lebende Architektur-Referenz in
[CLAUDE.md](../../CLAUDE.md).

| ADR | Titel | Status |
|----:|-------|--------|
| [0001](0001-versionsfester-rng-vertrag.md) | Versionsfester RNG-Vertrag (`PCG64` + `bdo-v1`) | Angenommen (Sprint 39 / R-001) |
| [0002](0002-anwendungsseitig-append-only-audit-trail.md) | Anwendungsseitig append-only Audit-Trail | Angenommen (Sprint 2, präzisiert Sprint 52 / S2.7) |
| [0003](0003-db-migrationen.md) | Versionierte, atomare SQLite-Migrationen | Angenommen (Sprint 2, atomar seit Sprint 45 / A-002) |
| [0004](0004-pyqt-lizenz-und-distributions-scope.md) | PyQt6-Lizenz & Distributions-Scope | Akzeptiert (vorbehaltlich BDO-Legal, Sprint 63 / S-006) |

**Format.** Titel / Status / Kontext / Entscheidung / Konsequenzen. Neue ADRs
fortlaufend nummerieren (`NNNN-kurz-titel.md`). Eine getroffene Entscheidung wird
nicht editiert, sondern bei Bedarf durch eine neue ADR ersetzt (Status der alten
auf „Abgelöst durch …" setzen).
