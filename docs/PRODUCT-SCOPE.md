# MovieHub Product Scope and Architecture

> **Document status — 2026-11-27:** This document preserves the original first-release scope for historical context, but the old implementation table and remaining-delivery list have been superseded. The shipped product is in maintenance mode. Current production facts are maintained in [PROJECT-STATUS.md](PROJECT-STATUS.md).

## Current shipped scope

MovieHub is a self-hosted, single-user movie discovery and chart-history application. Its primary journey is:

**Open a supported chart → discover a title → view details → open Xiaoya search.**

Current production charts are Douban Top 250 and the four imported 2025 annual lists. Douban real-time popular and high-rated were part of the early proposal but were retired after the target endpoint was found disallowed by robots.txt; they are not current product commitments.

Current functionality includes chart snapshots/history and rank comparison, local catalogue search/filtering, title details, posters, favorites, TMDB-backed online discovery, and a configurable Xiaoya handoff. The current rating display uses IMDb ratings where available; TMDB remains a discovery and metadata provider. See [PROJECT-STATUS.md](PROJECT-STATUS.md) for exact production coverage.

MovieHub is not a download client, media server, media-library manager, or video player. Existing Xiaoya, Jellyfin and SmartStrm services keep those responsibilities. MovieHub must not duplicate or interfere with them.

## Original first-release scope (historical)

The following records the original planning baseline. Items superseded by the current shipped scope above are historical requirements, not a promise that every proposed source or feature was delivered.

### 1. Chart discovery

The original proposal listed:

- Douban Top 250
- Douban real-time popular
- Douban high-rated
- Annual charts, including 2025 and 2026 as seeded definitions

**Scope correction:** only Top 250 and the four verified/imported 2025 annual lists are current supported chart data. Popular/high-rated were retired for source-policy reasons. A 2026 chart definition or dataset must wait for official publication and verification.

### 2. Movie search and filters

The intended catalogue search covers display/original title and filters for media type, rating, rating count, year, genres and regions. Search uses the application-owned SQLite database; external search infrastructure is not required.

### 3. Movie detail

Show available metadata without inventing missing values, including display/original title, year, media type, source-specific ratings, genres, regions, directors, actors, overview, external identifiers, source links and cached posters where available.

### 4. Favorites

Single-user self-hosted favorites; no account/user system is required. Favorite writes use MovieHub internal movie IDs, never provider IDs.

### 5. Xiaoya handoff

Provide a configurable link to the existing Xiaoya search UI, passing the title through the configured query parameter. This is a handoff, not a MovieHub download, playback, or media-library integration.

## Explicit exclusions

Do not implement these as part of MovieHub's current scope:

- Downloading, download queues, torrent/BT or cloud-drive transfer.
- Media-library scanning, organization, renaming or playback metadata management.
- Video playback, transcoding, subtitle management or streaming.
- Replacing Xiaoya, Jellyfin or SmartStrm.
- User accounts, multi-user roles or public social features.
- Redis, MySQL, PostgreSQL or Elasticsearch merely to expand infrastructure.

## Architecture

- Frontend: React + TypeScript + Vite, built and served as a separate frontend container.
- Backend: FastAPI in its own container.
- Database: one MovieHub-owned SQLite database; internal foreign keys use MovieHub IDs.
- Search: SQLite-backed local catalogue search; no external search service is required.
- Posters: MovieHub-managed local cache on the persistent data volume.
- Import: Douban Scout is an external, read-only import source. The MovieHub container receives its staged source directory read-only.
- Reverse proxy: existing Nginx Proxy Manager; use same-origin routing for frontend/API where configured.
- Keep frontend and backend on the existing Docker network boundary. Do not publish unnecessary NAS/LAN host ports.
- Do not introduce extra always-on infrastructure beyond the application containers and SQLite.

## Data-source and safety policy

- Use only chart sources that pass source/permission and robots.txt review.
- Do not run the retired popular/high-rated collectors or attempt to bypass their access restrictions.
- Keep source-specific ratings and metadata separate; never treat ratings from different providers as interchangeable.
- Preserve field-level provenance and leave missing or ambiguous values missing.
- Never use the Douban Scout database as MovieHub's database or write to the Scout source.
- Do not change, restart or reconfigure Xiaoya, Jellyfin, SmartStrm, NPM or NAS services as part of ordinary code development.
- Do not commit secrets, production databases, backup archives, or private environment files.

## Historical delivery plan

The earlier phase-by-phase implementation table, CI counts, migration checklist and delivery order were removed from this document because they became stale as the project evolved. Consult [DEVELOPMENT-PROGRESS.md](DEVELOPMENT-PROGRESS.md) for historical milestones and [PROJECT-STATUS.md](PROJECT-STATUS.md) for the current verified state.
