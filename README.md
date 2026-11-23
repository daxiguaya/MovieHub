# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: annual chart data acquisition and pre-deployment validation. The official 2025 annual roundup now has a one-shot collector that emits four separate normalized snapshots and checks robots.txt before fetching. Isolated 10k/100k SQLite search and Scout import benchmarks completed in CI #314.
- Latest standard CI [#325](https://github.com/daxiguaya/MovieHub/actions/runs/45166104334) passes: backend tests, annual collection plus four dry-runs, frontend tests/build and Chromium E2E all succeeded. The opt-in performance job was skipped in #325; the 10k/100k LIKE-search and Scout-import benchmarks last ran successfully in #314. Built-in chart import preflight enforces category, period and movie/TV consistency before database access. The 2025 annual collector produced four separate snapshots (8/10/10/10 entries); the downloaded artifact has also passed an independent 38-entry structural and cross-list review. A read-only Scout coverage audit is implemented with explicit handling for unexpected media types and duplicate Scout IDs; it still needs a separately staged Scout copy and CI validation on the latest branch head. Metadata enrichment, explicit snapshot imports, 2026 publication review, NPM verification and production rollout remain outstanding.
- Estimated first-release progress: about 68%; this is a planning estimate, not a test metric.
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
