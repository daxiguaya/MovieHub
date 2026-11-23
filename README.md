# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: annual chart data acquisition and pre-deployment validation. The official 2025 annual roundup now has a one-shot collector that emits four separate normalized snapshots and checks robots.txt before fetching. Isolated 10k/100k SQLite search and Scout import benchmarks completed in CI #314.
- Latest full CI [#314](https://github.com/daxiguaya/MovieHub/actions/runs/45152308824) passes: backend tests, frontend tests/build, Chromium E2E and the opt-in performance job all succeeded. The performance run measured 10k/100k LIKE search and Scout import throughput; details and limitations are recorded in the development progress document. Built-in chart import preflight enforces category, period and movie/TV consistency before database access. The 2025 annual catalogue is split into four distinct official categories; the collector has completed a robots-permitted live collection, generated 8/10/10/10 entries, and passed all four dry-runs. Metadata enrichment and explicit snapshot imports remain outstanding, as do 2026 publication review, NPM verification and production rollout.
- Estimated first-release progress: about 66%; this is a planning estimate, not a test metric.
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
- [Scout import runbook](docs/SCOUT-IMPORT.md)

## Safety model

- MovieHub owns a separate database; it does not migrate or modify Douban Scout.
- Scout is treated as a read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production deployment and migration require a separate reviewed procedure.
