# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: annual chart data acquisition, SQLite search/Scout import performance measurements and pre-deployment validation. A manual GitHub Actions benchmark workflow now runs isolated 10k/100k tests; measurements are pending. Built-in chart imports receive category/period/media-type preflight validation before database access.
- Latest CI #305 passes: 110 backend tests (2 opt-in benchmarks skipped), 5 Vitest UI tests and 4 Playwright Chromium E2E tests, including a live FastAPI + temporary SQLite integration. Built-in chart import preflight now enforces category, period and movie/TV consistency before database access. The 2025 annual catalogue is split into four distinct official categories; source data import, 2026 publication review, NPM verification and production rollout remain outstanding.
- Estimated first-release progress: about 62%; this is a planning estimate, not a test metric.
- Backend and frontend regression/build checks run on GitHub Actions for pushes to the active development branch.

See [development progress](docs/DEVELOPMENT-PROGRESS.md) for the current checklist and CI result.

## Documentation

- [Database design](docs/phase4-database-design.md)
- [Configuration and database lifecycle](docs/CONFIGURATION.md)
- [Frontend/backend container deployment](docs/DEPLOYMENT.md)
- [Database backup and restore](docs/BACKUP-RESTORE.md)
- [Product scope and architecture](docs/PRODUCT-SCOPE.md)
- [Chart snapshot import](docs/CHART-IMPORT.md)
- [Chart source policy](docs/CHART-SOURCES.md)
- [Scout import runbook](docs/SCOUT-IMPORT.md)

## Safety model

- MovieHub owns a separate database; it does not migrate or modify Douban Scout.
- Scout is treated as a read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production deployment and migration require a separate reviewed procedure.
