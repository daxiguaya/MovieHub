# MovieHub Product Scope and Architecture

Status: agreed first-release product baseline
Branch: phase4/database-foundation
Last updated: 2026-11-23

## Product definition

MovieHub is a self-hosted movie discovery and chart-history application. Its primary journey is:

**Open a chart → discover a movie → view its details → open Xiaoya search.**

MovieHub is not a download client, media server, media-library manager, or video player. Existing Xiaoya, Jellyfin and SmartStrm services keep those responsibilities. MovieHub must not duplicate or interfere with them.

## First-release features

### 1. Chart discovery

Initial chart groups:

- Douban Top 250
- Douban real-time popular
- Douban high-rated
- Annual charts, including 2025 and 2026 as seeded definitions

Requirements:

- Chart landing page with clear chart grouping and poster-led cards.
- Chart detail page with rank, title, year, rating, genres and poster.
- Latest snapshot by default.
- Historical snapshot date selector.
- Stable chart slugs and date-specific snapshots; importing one date must not erase other dates.

### 2. Movie search and filters

- Search display title and original title.
- Filter movie/TV type, rating range, rating count, year range, genres, excluded genres and regions.
- Sort by rating, rating count or year.
- Cursor pagination.
- Start with the existing SQLite LIKE-based title/original-title search and benchmark it against realistic catalogue sizes.
- FTS5 is optional, not a hard runtime dependency: add it only if measured search latency or relevance justifies the added schema/index complexity, with a tested LIKE fallback.
- Do not add Redis, MySQL or Elasticsearch.

### 3. Movie detail

Show available metadata without inventing missing values:

- Display/original title, year, movie or TV type.
- Douban rating and rating count.
- Genres and regions.
- Directors, actors and overview.
- External identifiers and Douban detail link when present.
- Poster gallery backed by MovieHub's local poster cache.

### 4. Favorites

- Single-user self-hosted favorites; no account/user system in the first release.
- Add/remove a movie and list saved movies.
- Optional user note may be supported by the existing favorites.note column.
- Favorite writes must use MovieHub internal movies.id, never a provider ID.

### 5. Xiaoya handoff

- Provide a clear “Search in Xiaoya” action on movie detail and movie cards where useful.
- Open the existing Xiaoya web search page in a new browser tab/window, passing the movie title through the existing box query parameter with proper URL encoding.
- Make the Xiaoya base/search URL configurable. Do not hardcode the user's NAS hostname into application source or expose credentials.
- This is a handoff to Xiaoya's existing search UI, not a MovieHub resource search, download, playback or media-library integration.

## Explicit exclusions

Do not implement these in MovieHub first release:

- Downloading, download queue, torrent/BT or cloud-drive transfer.
- Media-library scanning, organization, renaming or metadata management for playback libraries.
- Video playback, transcoding, subtitle management or streaming.
- Replacing Xiaoya, Jellyfin or SmartStrm.
- User accounts, multi-user roles or public social features.
- Redis, MySQL, PostgreSQL or Elasticsearch.

## Technology and deployment architecture

- Frontend: React + TypeScript + Vite, built and served as a separate frontend container.
- Backend: FastAPI in its own container.
- Database: one MovieHub-owned SQLite database; internal foreign keys use MovieHub IDs.
- Search: SQLite LIKE by default; optional FTS5 only if benchmarks justify it, with no external search service.
- Posters: MovieHub-managed local cache on the persistent data volume.
- Import: Douban Scout is an external, read-only import source. The MovieHub container receives its export/source directory read-only.
- Reverse proxy: existing Nginx Proxy Manager; prefer one same-origin MovieHub host with frontend routes and an /api reverse-proxy route, avoiding broad CORS.
- Keep frontend and backend on the existing Docker network boundary. Do not publish an unnecessary NAS/LAN host port.
- Do not introduce extra always-on infrastructure beyond the two application containers and SQLite.

## Current implementation coverage (as of 2026-11-24)

| Capability | Current state | Remaining work |
|---|---|---|
| Independent SQLite schema | Complete, 11 core tables; schema v2 includes durable import-batch receipts; latest backend CI passes | Validate v1 → v2 migration against an isolated copy of a real v1 MovieHub database before production use |
| Chart definitions and dated snapshots | Backend API, date-scoped snapshots, normalized JSON CLI import, dry-run, rank comparison API/UI, robots-aware Top 250/popular/high-rated collectors and official 2025 annual collector exist | Review/import actual 2025 snapshots into an isolated MovieHub DB; verify 2026 categories and publication data; decide whether a refresh mechanism is warranted |
| Movie search/filter API | Implemented with SQL LIKE and cursor pagination | Run opt-in realistic 10k/100k latency benchmarks; add FTS5 only if measured results justify it |
| Movie detail API | Implemented; internal MovieHub IDs are used for relations | Real-data visual/UX validation |
| Poster cache/API | Implemented with source-host allowlist, redirect/DNS validation, response-size and image-signature checks | Visual QA of loading, missing and failed poster states |
| Favorites | Protected list/add/update-note/remove API uses MovieHub internal IDs; frontend UI and browser flow implemented | Verify protected key injection through an isolated NPM test host |
| Scout import | Read-only source boundary, identity/numeric gates, 500-record transactions, per-record SAVEPOINT isolation, merge/partial retry, durable receipts, journal, error manifest, preview/reconciliation and readiness CLI; latest backend CI passes | Audit a consistent staged Scout copy, reconcile its preview, then validate throughput on controlled hardware |
| React frontend | Chart discovery/history/comparison, search/filter, detail, favorites and configurable Xiaoya handoff; 5 frontend tests and 4 Playwright E2E tests pass | Visual/responsive QA and review against representative real catalogue data |
| Frontend/backend Compose topology | Separate frontend/backend services, same-origin routing documented; both images build in CI | Verify actual NPM locations, TLS/access controls and server-side favorites-key injection during authorized rollout |
| Backup/restore | SQLite online backup, integrity/foreign-key checks, manifest, retention, guarded restore and rollback utility/runbook implemented | Rehearse against an isolated test database and verify the intended NAS backup destination during authorized rollout |
| Production rollout | Not deployed; no production DB, NPM or NAS service modified | Separate approval, deployment checklist, staged smoke test and rollback plan |

Latest full CI: [run #45212034805](https://github.com/daxiguaya/MovieHub/actions/runs/45212034805) — backend 224 passed / 4 skipped, frontend 5 passed, browser E2E 4 passed. Annual collection and performance benchmark jobs were skipped by workflow conditions and remain unverified.
## Chart acquisition policy

- Use normalized snapshot imports until an authorized and reliable chart provider is selected.
- Do not rely on deprecated public API keys, mandatory paid proxies, or high-frequency scraping.
- Keep source adapters isolated and preserve source attribution, pacing, cache and retry boundaries.

## Remaining delivery order

1. Validate the schema-v1 migration using a consistent, isolated copy of a real v1 MovieHub database; do not use the live NAS database as a test fixture.
2. Run the read-only Scout whole-catalogue audit and chart-coverage gate against a consistent staged Scout copy, then generate and reconcile an import preview.
3. Review the official 2025 four-chart snapshots and import them only into a fresh isolated MovieHub database before considering any production data operation.
4. Verify 2026 chart definitions against official publication sources and decide whether scheduled refresh is actually required for the first release.
5. Complete visual/responsive QA and realistic-data UX review for charts, search, details, posters and favorites.
6. Validate same-origin NPM routing, TLS/access controls and favorites-only server-side API-key injection in an isolated test host.
7. Run opt-in 10k/100k search/import benchmarks and an isolated backup/restore rehearsal; record results separately from CI.
8. Only after the above review, prepare a deployment checklist and rollback plan. Production initialization, Scout import, NPM changes and service restarts remain separate operator actions requiring explicit approval.

## Safety and compatibility

- Never use the Douban Scout database as MovieHub's database.
- Never write to the live Scout source. Keep Scout mounts read-only and import tests fixture-based.
- Do not change, restart or reconfigure Xiaoya, Jellyfin, SmartStrm, NPM or NAS services as part of code development.
- Do not deploy or initialize a production database without a separate explicit authorization.
- Do not commit secrets, real database files, backup archives or private environment files.
