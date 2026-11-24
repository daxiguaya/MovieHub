# MovieHub

A self-hosted movie discovery and chart-history service with its own independent SQLite database.

## Project status

- **Current stage:** pre-deployment hardening. MovieHub has not been deployed; its production database has not been created.
- **Overall first-release progress:** about 75% (planning estimate, not a test metric).
- **Completed:** independent SQLite schema/initializer/migrations, core FastAPI APIs, React frontend core flows, chart collectors/import pipeline, Docker packaging, backup/restore tooling and automated tests.
- **Real-data validation:** four official 2025 Douban annual charts (38 records) were imported into a newly initialized disposable SQLite database in GitHub Actions. This is a real-data rehearsal, not a production import or Scout catalogue audit.
- **Latest CI:** [#45312384087](https://github.com/daxiguaya/MovieHub/actions/runs/45312384087) succeeded: backend 247 passed / 4 skipped, frontend 5 passed, Chromium E2E 4 passed. The real-data rehearsal job was skipped in this docs-only run; its latest successful run is [#45312215353](https://github.com/daxiguaya/MovieHub/actions/runs/45312215353).
- **Remaining:** enrich and review first-release data, complete visual QA, run an isolated deployment/backup/restore rehearsal, verify NPM/Xiaoya integration, and then separately approve NAS production deployment.
- **Scout clarification:** Scout is an optional external read-only metadata source. There is no MovieHub source database yet, and a Scout full-catalogue audit is not a prerequisite for MovieHub database initialization or development.

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
