# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: annual chart data acquisition, opt-in Scout import performance benchmarks and pre-deployment validation. Built-in chart imports now receive category/period/media-type preflight validation before database access.
- The frontend now has 5 Vitest UI tests and 4 Playwright Chromium browser E2E tests passing in CI, including a live FastAPI + temporary SQLite integration. The 2025 annual catalogue is split into four distinct official categories; source data import, 2026 publication review, NPM verification and production rollout remain outstanding.
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
