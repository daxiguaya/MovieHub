# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: first-release feature implementation; the React frontend and dual-container packaging are now in progress.
- Estimated first-release progress: about 54%; frontend pages and automatic chart collection are not yet complete.
- The backend test suite runs on GitHub Actions for pushes to the active development branch.

See [development progress](docs/DEVELOPMENT-PROGRESS.md) for the current checklist and CI result.

## Documentation

- [Database design](docs/phase4-database-design.md)
- [Configuration and database lifecycle](docs/CONFIGURATION.md)
- [Backend container deployment](docs/DEPLOYMENT.md)
- [Database backup and restore](docs/BACKUP-RESTORE.md)
- [Product scope and architecture](docs/PRODUCT-SCOPE.md)
- [Chart snapshot import](docs/CHART-IMPORT.md)
- [Chart source policy](docs/CHART-SOURCES.md)

## Safety model

- MovieHub owns a separate database; it does not migrate or modify Douban Scout.
- Scout is treated as a read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production deployment and migration require a separate reviewed procedure.
