# MovieHub

A self-hosted movie discovery and chart-history service with its own SQLite database.

## Project status

- Phase 4 database foundation: complete.
- Application integration audit: complete.
- Current work: first-release feature implementation; product scope and architecture are documented.
- Estimated first-release progress: about 40%; frontend and production deployment are not yet implemented.
- The backend test suite runs on GitHub Actions for pushes to the active development branch.

See [development progress](docs/DEVELOPMENT-PROGRESS.md) for the current checklist and CI result.

## Documentation

- [Database design](docs/phase4-database-design.md)
- [Configuration and database lifecycle](docs/CONFIGURATION.md)
- [Backend container deployment](docs/DEPLOYMENT.md)
- [Database backup and restore](docs/BACKUP-RESTORE.md)
- [Product scope and architecture](docs/PRODUCT-SCOPE.md)

## Safety model

- MovieHub owns a separate database; it does not migrate or modify Douban Scout.
- Scout is treated as a read-only import source.
- Database initialization is explicit; application startup does not create a database.
- Production deployment and migration require a separate reviewed procedure.
