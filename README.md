# MovieHub

A self-hosted movie discovery and chart-history service with its own independent SQLite database.

## Project status

- **Current stage:** 核心功能已部署，进入真实数据、搜索体验与生产验收收尾。
- **Deployed code baseline:** `main` commit `c2ffdd8` (2026-11-25). NAS production uses the independent MovieHub database at `/volume1/docker/moviehub/data` and backup directory `/volume1/docker/moviehub/backup`.
- **Live service acceptance:** frontend and backend containers both report healthy; `/moviehub/`, `/moviehub/search`, and `/moviehub/api/ready` return HTTP 200 through the existing NPM HTTPS host. Import routes are denied with HTTP 404; the existing DSM root route remains HTTP 200. The `/moviehub` redirect preserves the external `:18443` port.
- **Database/metadata acceptance:** production database schema v4 is deployed. TMDB synopsis import wrote 238 records; a read-only production audit verified 238 matching TMDB provenance rows and 238/238 SHA-256 matches. SQLite integrity check returned `ok`. This does not imply every chart snapshot or every movie metadata field has been populated.
- **Real-data validation:** 5 source snapshots / 288 chart rows / 288 unique titles passed isolated import and browser journeys. Production chart-snapshot coverage must be read from the current database audit, not inferred from the isolated CI run.
- **Remaining:** complete production UI acceptance for search sorting, favorites/API-key flow, Xiaoya jump, chart pagination/history, and update any remaining stale operational documentation.
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
