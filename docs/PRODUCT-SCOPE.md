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

## Current implementation coverage (as of 2026-11-23)

| Capability | Current state | Remaining work |
|---|---|---|
| Independent SQLite schema | Complete, 11 core tables | Add a versioned search/index migration only if benchmarks justify it |
| Chart definitions and dated snapshots | Backend API, date-scoped snapshots, normalized JSON CLI import, dry-run, rank comparison API/UI and a robots-aware one-shot Top 250 collector exist | Popular/high-rated/annual collectors, scheduled refresh and live-data UX validation |
| Movie search/filter API | Exists; title matching uses SQL LIKE | Benchmark with realistic fixture sizes; keep FTS5 optional |
| Movie detail API | Exists | Frontend detail view and Xiaoya handoff |
| Poster cache/API | Exists; source URL allowlist, redirect validation, public-DNS check and 8 MiB streaming cap added | Frontend image states and cache UX |
| Favorites | Protected list/add/update-note/remove API implemented using MovieHub internal IDs; 70-test CI passed | Frontend UI |
| Scout import | Read-only import, timestamp-based incremental skip, forced full reprocessing, 500-record transaction batches, per-record SAVEPOINT isolation; merge, partial-retry and 1,000-row fixture tests | 10k/100k and target-NAS performance validation |
| React frontend | Discovery, chart history/comparison, full search/filter, internal-ID detail, favorites and configurable Xiaoya handoff implemented; 5 UI tests and separate container build pass in CI | Full-stack browser E2E, real-data UX validation and visual polish |
| Frontend/backend Compose topology | Separate frontend and backend services; same-origin NPM routing documented | Verify actual NPM locations and server-side favorites-key injection during authorized rollout |
| Backup/restore | Utility, tests and runbook exist | Validate real backup destination only during an authorized rollout |

## Chart acquisition policy

- Use normalized snapshot imports until an authorized and reliable chart provider is selected.
- Do not rely on deprecated public API keys, mandatory paid proxies, or high-frequency scraping.
- Keep source adapters isolated and preserve source attribution, pacing, cache and retry boundaries.

## Delivery order

1. Benchmark existing LIKE search on realistic fixtures; only add optional FTS5 if measurements show it is needed.
2. Complete protected favorites API validation, then implement the frontend API client.
3. Define a stable frontend API client and error/loading/empty states.
4. Build the React + TypeScript + Vite pages: chart home, chart snapshot, movie search/filter, movie detail and favorites.
5. Add a separate frontend container and Compose service; keep API internal and route /api through the same NPM host.
6. Add configurable Xiaoya search handoff.
7. Run end-to-end tests against temporary databases and test fixtures.
8. Only after review, plan NAS deployment, Scout import, NPM routing and production initialization as separate operator actions.

## Safety and compatibility

- Never use the Douban Scout database as MovieHub's database.
- Never write to the live Scout source. Keep Scout mounts read-only and import tests fixture-based.
- Do not change, restart or reconfigure Xiaoya, Jellyfin, SmartStrm, NPM or NAS services as part of code development.
- Do not deploy or initialize a production database without a separate explicit authorization.
- Do not commit secrets, real database files, backup archives or private environment files.
