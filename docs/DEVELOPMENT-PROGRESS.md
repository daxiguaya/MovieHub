# MovieHub Development Progress

Branch: `phase4/database-foundation`
Last updated: 2026-11-23
Current phase: Post-Phase-4 application integration audit

## Phase 4 — independent database foundation

- [x] Define the independent MovieHub SQLite schema (11 core tables); external provider IDs remain nullable identifiers and internal relations use `movies.id`.
- [x] Add explicit database initialization from an empty database, with validation and atomic publication; application import/startup does not silently create a database.
- [x] Validate SQL schema against SQLAlchemy ORM metadata, including core constraints, indexes and foreign-key behavior.
- [x] Add migration safety: schema version checks, verified backup, integrity/foreign-key validation and rollback restoration.
- [x] Implement chart snapshot semantics: re-import replaces only the selected chart/date snapshot, preserves other dates and does not overwrite populated Scout metadata.
- [x] Cover failure rollback, WAL sidecar cleanup and idempotent built-in chart initialization without overwriting user settings.
- [x] Add direct read-only Douban Scout fixture integration coverage for source-field mapping, MovieHub internal IDs, genre/region associations, posters, movie/TV records, and source-file immutability.

**Phase 4: 7/7 complete.**

## Application integration audit

- [x] Prevent API database dependency from silently creating a missing SQLite file; missing DB now returns HTTP 503 with explicit initialization guidance.
- [x] Verify uninitialized database requests return HTTP 503 without creating the database path or parent directory.
- [x] Verify chart and movie read APIs return successfully against a temporary database created by the explicit initializer.
- [x] Verify protected import endpoints reject missing API keys and block absolute-path and symlink escapes from the configured import directory.
- [x] Verify chart snapshot import, same-date replacement, historical-date listing and latest-snapshot reads through the HTTP API.
- [x] Remove wildcard credentialed CORS; cross-origin access is disabled by default and configurable through an explicit origin allowlist.
- [x] Add a read-only /api/ready check that verifies all required tables and schema version; keep /api/health as the process liveness check.
- [x] Review console logging configuration and graceful cancellation of the poster-cache cleanup task; no service restart or deployment performed.
- [x] Remove obsolete tracked Phase 3 repair-backup copies and the one-off source-repair script; add ignore rules for local repair and migration artifacts.
- [x] Add configuration documentation, safe backend environment template and project README links.

**Application integration audit: complete.**

## Next work

- [ ] Decide and implement deployment packaging (Dockerfile/Compose, mounts, health checks and reverse-proxy assumptions) after the runtime/frontend layout is finalized.
- [ ] Continue feature/API work on the independent MovieHub database; keep all development validation on temporary fixtures.
- [ ] Keep production database creation, migration, import and deployment as a separately reviewed operation.

## Latest code validation

- Workflow: Backend tests
- Run: [#62](https://github.com/daxiguaya/MovieHub/actions/runs/45125409205)
- Tested commit: `7f14f7f564621f2acb5c9b53936c5bf2674a83de`
- Result: **success** — backend compilation passed; **32 tests passed**. One non-blocking Starlette/httpx TestClient deprecation warning remains.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, or service restart is part of this audit.
- Keep validation on temporary fixtures. Do not touch the user's live Scout database.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.
