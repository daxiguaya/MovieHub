# MovieHub

A self-hosted movie discovery and chart-history service with its own independent SQLite database.

## Project status

- **Current stage:** NAS deployment completed; live acceptance and first-release data population are in progress.
- **Deployed code baseline:** `main` commit `1c6ceff` (2026-11-24). NAS deployment uses the independent MovieHub database at `/volume1/docker/moviehub/data` and backup directory `/volume1/docker/moviehub/backup`.
- **Live service acceptance:** frontend and backend containers both report healthy; `/moviehub/`, `/moviehub/search`, and `/moviehub/api/ready` return HTTP 200 through the existing NPM HTTPS host. Import routes are denied with HTTP 404; the existing DSM root route remains HTTP 200. The `/moviehub` redirect preserves the external `:18443` port.
- **Database/backup acceptance:** schema v3 is ready; the first backup's manifest size and SHA-256 match, SQLite integrity is `ok`, foreign-key errors are zero, and a temporary-file restore rehearsal passed with all 13 table row counts identical. The production database currently contains 7 built-in chart definitions but no movie catalogue or imported chart snapshots yet.
- **Real-data validation:** 5 source snapshots / 288 chart rows / 288 unique titles passed disposable GitHub Actions import and browser journeys. These records have not yet been imported into the NAS production database.
- **Remaining:** confirm API-key rotation end-to-end, decide TMDB overview persistence only after terms review, import approved first-launch chart data, complete visual/edge-state QA, and verify Xiaoya integration.
- **Scout clarification:** Scout remains an optional external read-only metadata source, not MovieHub's source database or a prerequisite for the deployed application.

See [the canonical project status and delivery checklist](docs/PROJECT-STATUS.md) for the complete done/remaining list and progress estimate, and [the detailed development history](docs/DEVELOPMENT-PROGRESS.md) for milestones.

## Documentation

- [Project status and delivery checklist](docs/PROJECT-STATUS.md)
- [Development progress history](docs/DEVELOPMENT-PROGRESS.md)
- [Database design](docs/phase4-database-design.md)
- [Configuration and database lifecycle](docs/CONFIGURATION.md)
- [Frontend/backend container deployment](docs/DEPLOYMENT.md)
- [Database backup and restore](docs/BACKUP-RESTORE.md)
- [Product scope and architecture](docs/PRODUCT-SCOPE.md)
- [Chart snapshot import](docs/CHART-IMPORT.md)
- [Chart source policy](docs/CHART-SOURCES.md)
- [Official 2025 annual chart collector](docs/ANNUAL-CHART-COLLECTOR.md)
- [2025 annual chart artifact review](docs/ANNUAL-2025-ARTIFACT-REVIEW.md)
- [Scout import runbook](docs/SCOUT-IMPORT.md)
- [Read-only Scout chart coverage audit](docs/SCOUT-CHART-COVERAGE.md)

## Safety model

- MovieHub owns a new, independent SQLite database; it does not migrate or modify another application's database.
- Scout, if enabled later, is treated as an optional read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production database initialization, deployment, NPM changes and service restarts require a separately reviewed and approved procedure.
