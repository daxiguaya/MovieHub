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
- Search must use SQLite FTS5 when available in the completed implementation; do not add Redis, MySQL or Elasticsearch.
- Keep a safe fallback strategy for SQLite builds without FTS5, and test both supported behavior and clear failure/diagnostics.

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
- Search: SQLite FTS5; no external search service.
- Posters: MovieHub-managed local cache on the persistent data volume.
- Import: Douban Scout is an external, read-only import source. The MovieHub container receives its export/source directory read-only.
- Reverse proxy: existing Nginx Proxy Manager; prefer one same-origin MovieHub host with frontend routes and an /api reverse-proxy route, avoiding broad CORS.
- Keep frontend and backend on the existing Docker network boundary. Do not publish an unnecessary NAS/LAN host port.
- Do not introduce extra always-on infrastructure beyond the two application containers and SQLite.

## Current implementation coverage (as of 2026-11-23)

| Capability | Current state | Remaining work |
|---|---|---|
| Independent SQLite schema | Complete, 11 core tables | Add reviewed versioned search/index migration |
| Chart definitions and dated snapshots | Backend API and seeded definitions exist | Frontend chart browsing and date selector |
| Movie search/filter API | Exists; currently title matching uses SQL LIKE | Implement FTS5 and test fallback |
| Movie detail API | Exists | Frontend detail view and Xiaoya handoff |
| Poster cache/API | Exists | Frontend image states and cache UX |
| Favorites | Database table exists | CRUD/list API, tests and UI |
| Scout import | Protected backend import API exists | Operator workflow and safe production import review |
| React frontend | Not present yet | Build frontend application and container |
| Frontend/backend Compose topology | Backend-only Compose exists | Add separate frontend service and same-origin NPM route documentation |
| Backup/restore | Utility, tests and runbook exist | Validate real backup destination only during an authorized rollout |

## Delivery order

1. Implement FTS5 as a versioned MovieHub migration, keeping the original 11-table core model stable and preserving LIKE fallback where required.
2. Add favorites list/add/remove API endpoints and integration tests.
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
