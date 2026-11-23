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
- [ ] Complete a direct read-only Douban Scout fixture integration test, verifying source-field mapping, internal MovieHub IDs and association/poster handling without modifying Scout data.

Progress: **6/7 checklist items complete**.

## Latest CI

- Workflow: Backend tests
- Run: [#24](https://github.com/daxiguaya/MovieHub/actions/runs/45123028732)
- Commit: `855e720dae91df057e243b6bd48ae4b1939d0c47`
- Result: **success** — compile passed; **24 tests passed**.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, or service restart is part of Phase 4.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.

## Next task

Implement and test the direct read-only Scout fixture integration path. Update this checklist and CI result whenever a milestone is completed.
