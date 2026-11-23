# MovieHub Development Progress

Branch: `phase4/database-foundation`
Last updated: 2026-11-23
Current phase: Phase 4 — independent database foundation

## Phase 4 checklist

- [x] Define the independent MovieHub SQLite schema (11 core tables); external provider IDs remain nullable identifiers and internal relations use `movies.id`.
- [x] Add explicit database initialization from an empty database, with validation and atomic publication; application import/startup does not silently create the database.
- [x] Validate SQL schema against SQLAlchemy ORM metadata, including core constraints, indexes and foreign-key behavior.
- [x] Add migration safety: schema version checks, verified backup, integrity/foreign-key validation and rollback restoration.
- [x] Implement chart snapshot semantics: re-import replaces only the selected chart/date snapshot, preserves other dates and does not overwrite populated Scout metadata.
- [x] Cover failure rollback, WAL sidecar cleanup and idempotent built-in chart initialization without overwriting user settings.
- [x] Add direct read-only Douban Scout fixture integration coverage for source-field mapping, MovieHub internal IDs, genre/region associations, posters, movie/TV records, and source-file immutability.

Progress: **7/7 checklist items complete — Phase 4 database foundation complete.**

## Latest code validation

- Workflow: Backend tests
- Run: [#27](https://github.com/daxiguaya/MovieHub/actions/runs/45123399908)
- Tested commit: `92ea20927e92d9beb4cd897c5b569921e10bb224`
- Result: **success** — backend compilation passed; **25 tests passed**.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, or service restart is part of Phase 4.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.

## Next phase

Phase 4 is complete. Before creating or migrating any production database, perform a separate application integration audit covering startup/database lifecycle, API dependencies, import workflows and chart/history queries. Keep all validation on temporary fixtures; do not touch the user's live Scout database or deploy services as part of this audit.
