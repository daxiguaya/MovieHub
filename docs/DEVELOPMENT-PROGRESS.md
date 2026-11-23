# MovieHub Development Progress

Branch: `phase4/database-foundation`
Last updated: 2026-11-23
Current phase: Frontend workflow implementation and chart acquisition

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
| Backend API baseline (charts, movie search/filter, details, posters, import, favorites) | 80% |
| Scout import hardening | Implementation and merge/partial-retry tests complete; large-fixture performance pending |
| Manual normalized chart snapshot import | Complete |
| Automatic chart collection and history comparison | 0% |
| Favorites API and frontend UI | Implemented; browser E2E pending |
| Xiaoya handoff | UI/config implemented; real NPM verification pending |
| React frontend and user workflows | Baseline implemented; browser E2E and visual QA pending |
| Container packaging and backup/restore preparation | 100% |
| Actual NAS deployment and end-to-end production verification | 0% |

**Estimated first-release implementation progress: about 54%.** This is a planning estimate, not a test metric. The independent database, core backend APIs, import hardening, poster security, frontend baseline and dual-container packaging are substantially in place; automatic chart collection, browser E2E validation and production rollout remain unfinished.

## Phase B — Scout import hardening (in progress)

- [x] Make `force_full` functional: incremental imports skip records whose Scout `update_time` is not newer than the last imported timestamp; forced full imports reprocess all valid records.
- [x] Replace the catalogue-wide write transaction with bounded batches (500 records per transaction) to reduce SQLite writer-lock duration.
- [x] Keep per-record SAVEPOINT isolation and make interrupted/partially committed imports safe to retry.
- [x] Invalidate MovieHub caches only after committed changes; report when earlier batches were committed before a later failure.
- [x] Add regression coverage proving incremental skip and forced full reprocessing behavior.

**Import hardening milestone: implemented and tested.** Remaining Phase B work is larger-fixture performance validation and an operator workflow. Source deletions remain non-destructive: absent Scout rows do not delete MovieHub movies.

## Favorites API milestone

- [x] Add protected favorites list/add/update-note/remove endpoints using internal MovieHub IDs, with idempotent writes and API-key enforcement.
- [x] Add integration tests for authentication, duplicate writes, note updates, internal-ID enforcement and removal.
- [x] Document that the browser must not embed the API key; the reverse proxy must inject it server-side.

**Favorites API and frontend favorites workflow: implemented. Browser E2E validation remains outstanding.**

## Phase D — poster-fetch security hardening

- [x] Restrict poster sources to HTTPS `imgN.doubanio.com` image CDN hosts.
- [x] Reject URL credentials, non-standard ports, non-HTTPS schemes, IP literals and arbitrary hosts.
- [x] Disable automatic redirects and validate every redirect target against the same host policy.
- [x] Resolve allowed CDN hostnames and reject DNS answers containing private, loopback, link-local or reserved IP addresses.
- [x] Restrict responses to raster image MIME types and enforce an 8 MiB maximum using both Content-Length and streamed byte counting.
- [x] Add regression tests for URL allowlisting, private DNS answers and size policy.

**Poster-fetch security milestone: implemented; 70-test CI passed.** No external poster URL is fetched unless it passes the allowlist and DNS checks.

## Chart snapshot import workflow

- [x] Add a CLI to validate and import normalized local JSON chart snapshots into the independent MovieHub database.
- [x] Add a dry-run mode that validates the input without opening or modifying the database.
- [x] Support a generic local adapter that preserves the declared chart provider and a Cinephile adapter that labels its normalized export.
- [x] Fix the latent adapter package import path discovered by exercising the CLI.
- [x] Document snapshot format, date-scoped replacement, metadata precedence and explicit non-automation boundary.

**Snapshot import workflow: implemented and tested. This is a manual normalized-data import path, not an automated Douban collector.**

## Phase E — React frontend baseline

- [x] Add React + TypeScript + Vite application scaffold and typed API client.
- [x] Implement discovery home and chart-group tiles.
- [x] Implement chart snapshot page with historical date selection and cursor pagination.
- [x] Implement movie search page with keyword, movie/TV type, min/max rating, rating-count floor, year range, included/excluded genres, regions, sort direction and cursor pagination.
- [x] Add internal MovieHub movie-ID detail API and detail page with metadata, poster, Douban link and Xiaoya handoff.
- [x] Implement favorites list/add/remove UI against the protected favorites API.
- [x] Make Xiaoya search URL runtime-configurable; the title is URL-encoded into the existing `box` parameter and opens in a new tab.
- [x] Keep the API key out of frontend assets; document server-side NPM header injection only for the favorites path.
- [x] Add a separate non-root Nginx frontend container, read-only root filesystem, 128 MiB limit and Compose service.
- [x] Add CI type-check, Vite production build and frontend Docker image build.

**Frontend baseline: implemented and build-validated.** Browser end-to-end tests, real chart data, final visual tuning and actual NPM integration remain outstanding.

## Chart source review and acquisition policy

- [x] Review Cinéphile's chart taxonomy and scheduled-refresh concept without copying code or datasets.
- [x] Review Douban iDatabase's multi-source metadata and ID-translation concepts without copying unlicensed code.
- [x] Record that Scout is a read-only metadata source, not a chart collector.
- [x] Record the manual normalized snapshot workflow and explicitly distinguish it from automatic chart collection.
- [x] Document why legacy/unauthorized API keys and mandatory third-party proxy APIs are not accepted as the default acquisition path.

**Source review: complete. Automatic chart acquisition remains pending an authorized, reliable provider decision.**

## Next work

- [ ] Benchmark title/original-title LIKE search against realistic fixture sizes; keep FTS5 optional rather than a hard runtime dependency, and add it only if measurements justify it.
- [ ] Add browser end-to-end tests for chart navigation, search, detail, favorites and Xiaoya handoff.
- [x] Define a typed frontend API client and visible loading, empty and error states.
- [x] Test Scout field-level merge precedence: empty fields preserve enriched MovieHub metadata; source-row deletion does not delete MovieHub records.
- [x] Test partial batch failure: already committed batches remain durable and an incremental retry completes safely.
- [ ] Validate import throughput, memory use and batch-lock duration with a larger synthetic fixture.
- [ ] Before any NAS rollout, verify the actual NPM Docker network, Scout export path/read permissions, and host data/backup directory ownership.
- [ ] Prefer a separate physical volume or off-site destination for backups; same-volume backups do not protect against disk failure.
- [ ] Keep production database initialization, Scout import, deployment and NPM changes as separately reviewed operator actions.

## Latest code validation

- Workflow: Backend tests + Compose validation + Docker image build
- Run: [#174](https://github.com/daxiguaya/MovieHub/actions/runs/45131148396)
- Tested commit: `f44e831d3f7a6168ef0a311dc88eb4528967c831`
- Result: **success** — backend compilation and tests, Compose validation, backend image build, frontend TypeScript/Vite production build and frontend Docker image build all passed. The latest backend suite contains 70 tests; one non-blocking Starlette/httpx TestClient deprecation warning remains.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, import, NPM proxy change, or service restart is part of this work.
- Keep validation on temporary fixtures. Do not touch the user's live Scout database.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.
