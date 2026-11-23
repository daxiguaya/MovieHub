# MovieHub Development Progress

Branch: `phase4/database-foundation`
Last updated: 2026-11-23
Current phase: Backend feature APIs and data-source workflow; frontend implementation next

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

## Backend container packaging

- [x] Add a Python 3.11 slim backend Dockerfile; run as a non-root UID.
- [x] Add a Compose service with read-only root filesystem, dropped capabilities, no-new-privileges, resource/PID limits and dedicated writable volumes.
- [x] Keep MovieHub data, backup destination and Scout source paths separate; mount Scout import source read-only.
- [x] Connect API only to the existing NPM Docker network and Compose bridge; do not publish a NAS/LAN host port.
- [x] Add explicit one-shot database initialization instructions; container startup never initializes or migrates a database.
- [x] Add liveness/readiness health-check wiring and document proxy-header trust boundaries.
- [x] Extend CI to validate Compose configuration and build the backend image.
- [x] Document NAS preparation, directory permissions, NPM upstream and operational safety boundaries.

**Backend packaging baseline: complete. Not deployed.**

## Database backup and restore

- [x] Add SQLite online-backup utility for consistent backups while the API is running.
- [x] Verify database integrity, foreign keys, required tables and schema version before accepting a backup.
- [x] Write SHA-256 manifest and metadata; retain the newest seven backup generations by default.
- [x] Add guarded restore requiring explicit confirmation and an operator assertion that the API is stopped.
- [x] Create a pre-restore rollback copy and atomically replace/validate the restored database.
- [x] Cover backup snapshot consistency, restore/rollback behavior, tamper rejection, retention and incomplete-schema rejection with tests.
- [x] Document NAS backup-volume preparation and the backup/restore operator runbook.

**Backup/restore baseline: complete. Poster cache is intentionally excluded because it is rebuildable.**

## Product scope and architecture

- [x] Record the agreed first-release user journey: chart discovery → movie details → Xiaoya search.
- [x] Record first-release charts, search/filter, detail, poster, favorites and Xiaoya handoff requirements.
- [x] Explicitly exclude downloading, playback and media-library management; preserve Xiaoya/Jellyfin/SmartStrm responsibilities.
- [x] Confirm React + TypeScript + Vite frontend in a separate container, FastAPI backend, SQLite with optional FTS5 only if justified, local poster cache, and no Redis/MySQL/Elasticsearch.
- [x] Map current backend coverage and identify FTS5, favorites API, frontend and frontend container as remaining work.

**Product scope and architecture baseline: complete.**

## Overall first-release progress (estimate)

| Workstream | Status |
|---|---:|
| Database foundation and Scout-safe import boundary | 100% |
| Backend API baseline (charts, movie search/filter, details, posters, import) | 70% |
| Scout import hardening | 100% of current implementation milestone; additional merge/performance validation pending |
| Automatic chart collection and history comparison | 0% |\n| Favorites API | 100% of API milestone; frontend UI remains\n| Xiaoya handoff | 0% |\n| React frontend and user workflows | 0% |
| Container packaging and backup/restore preparation | 100% |
| Actual NAS deployment and end-to-end production verification | 0% |

**Estimated first-release implementation progress: about 47%.** This is a planning estimate, not a test metric. The independent database, core backend APIs, import hardening, poster security, and backend packaging are substantially in place; automatic chart collection, favorites API, frontend, Xiaoya handoff, and production rollout remain unfinished.

## Phase B — Scout import hardening (in progress)

- [x] Make `force_full` functional: incremental imports skip records whose Scout `update_time` is not newer than the last imported timestamp; forced full imports reprocess all valid records.
- [x] Replace the catalogue-wide write transaction with bounded batches (500 records per transaction) to reduce SQLite writer-lock duration.
- [x] Keep per-record SAVEPOINT isolation and make interrupted/partially committed imports safe to retry.
- [x] Invalidate MovieHub caches only after committed changes; report when earlier batches were committed before a later failure.
- [x] Add regression coverage proving incremental skip and forced full reprocessing behavior.

**Import hardening milestone: implemented; 66-test CI passed including favorites API integration.** Remaining Phase B work includes explicit merge-policy tests, operator workflow, and larger-fixture performance validation. Source deletions remain non-destructive: absent Scout rows do not delete MovieHub movies.

## Phase D — poster-fetch security hardening

- [x] Restrict poster sources to HTTPS `imgN.doubanio.com` image CDN hosts.
- [x] Reject URL credentials, non-standard ports, non-HTTPS schemes, IP literals and arbitrary hosts.
- [x] Disable automatic redirects and validate every redirect target against the same host policy.
- [x] Resolve allowed CDN hostnames and reject DNS answers containing private, loopback, link-local or reserved IP addresses.
- [x] Restrict responses to raster image MIME types and enforce an 8 MiB maximum using both Content-Length and streamed byte counting.
- [x] Add regression tests for URL allowlisting, private DNS answers and size policy.

**Poster-fetch security milestone: implemented; 66-test CI passed including favorites API integration.** No external poster URL is fetched unless it passes the allowlist and DNS checks.

## Next work

- [ ] Benchmark title/original-title LIKE search against realistic fixture sizes; keep FTS5 optional rather than a hard runtime dependency, and add it only if measurements justify it.
- [x] Add protected favorites list/add/update-note/remove endpoints using internal MovieHub IDs, with idempotent writes and API-key enforcement.
- [x] Add favorites API integration tests for authentication, duplicate writes, note updates, internal-ID enforcement and removal.
- [x] Document that the browser must not embed the API key; the reverse proxy must inject it server-side.
- [ ] Build the React + TypeScript + Vite frontend in a separate container; implement charts, search/filter, movie detail, favorites and Xiaoya handoff.
- [ ] Define stable frontend API client behavior, including loading, empty, validation and error states.
- [ ] Formalize Scout field-level merge precedence and test empty-field preservation, newer timestamps, and source-row deletion behavior.
- [ ] Validate import throughput, memory use and batch-lock duration with a larger synthetic fixture.
- [ ] Before any NAS rollout, verify the actual NPM Docker network, Scout export path/read permissions, and host data/backup directory ownership.
- [ ] Prefer a separate physical volume or off-site destination for backups; same-volume backups do not protect against disk failure.
- [ ] Keep production database initialization, Scout import, deployment and NPM changes as separately reviewed operator actions.

## Latest code validation

- Workflow: Backend tests + Compose validation + Docker image build
- Run: [#113](https://github.com/daxiguaya/MovieHub/actions/runs/45128900397)
- Tested commit: `799a41796f7360ea557578bb9a619ad3dbf7b54d`
- Result: **success** — backend compilation, **66 tests passed**, Compose configuration validation and backend Docker image build passed. One non-blocking Starlette/httpx TestClient deprecation warning remains.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, import, NPM proxy change, or service restart is part of this work.
- Keep validation on temporary fixtures. Do not touch the user's live Scout database.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.
