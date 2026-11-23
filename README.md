# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: annual chart data quality and metadata enrichment preparation. The 2025 annual collector emits four independent normalized snapshots with robots.txt checks and recoverable four-file output. The new batch importer validates all four files together; dry-run is database-free and writes require explicit `--apply`, using one all-or-nothing transaction. Isolated 10k/100k SQLite search and Scout import benchmarks completed in CI #314.
- Latest full CI [#45179520602](https://github.com/daxiguaya/MovieHub/actions/runs/45179520602) passed backend, frontend and Chromium E2E; annual collection and performance benchmarks were skipped by workflow conditions. The batch importer has additional identity/preflight and CLI tests in the current follow-up CI. The 2025 annual artifact contains 38 entries (8/10/10/10) and passed structural review; it has not been imported into a database. Read-only Scout coverage audit still needs a separately staged Scout copy and current-head CI validation. Metadata enrichment, 2026 publication review, NPM verification and production rollout remain outstanding.
- Estimated first-release progress: about 70%; this is a planning estimate, not a test metric.
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
- [Official 2025 annual chart collector](docs/ANNUAL-CHART-COLLECTOR.md)
- [2025 annual chart artifact review](docs/ANNUAL-2025-ARTIFACT-REVIEW.md)
- [Scout import runbook](docs/SCOUT-IMPORT.md)
- [Read-only Scout chart coverage audit](docs/SCOUT-CHART-COVERAGE.md)

## Safety model

- MovieHub owns a separate database; it does not migrate or modify Douban Scout.
- Scout is treated as a read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production deployment and migration require a separate reviewed procedure.
