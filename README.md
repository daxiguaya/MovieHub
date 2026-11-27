# MovieHub

MovieHub is a self-hosted, single-user movie and TV discovery application with chart snapshots, searchable metadata, favorites, and a handoff to an existing Xiaoya search page. It keeps its own SQLite database and does not replace a media server or downloader.

## Project status

- **Repository:** [daxiguaya/MovieHub](https://github.com/daxiguaya/MovieHub)
- **Default branch:** `main`
- **Production feature baseline:** `f8d23cc00e4f860217c2fc6838ac73f4ac7ddcc` (2026-11-26)
- **Production database schema:** **v5** (confirmed by the 2026-11-25/26 production audit).
- **Production catalogue:** 288 movies/TV entries; Douban IDs 288/288, IMDb IDs 263/288, TMDB IDs 263/288.
- **Chart snapshots:** Douban Top 250 (250 entries) plus four 2025 annual charts (8/10/10/10 entries; 38 total). The annual lists are separate charts and retain their source ranks.
- **Metadata coverage:** overview 238/288; year 283/288; original title 258/288; directors 276/288; actors 268/288; posters 288/288. Missing source values remain missing rather than being inferred.
- **Ratings:** the UI displays IMDb ratings where available; TMDB remains a metadata/discovery source and its rating is not presented as the movie rating. IMDb rating data is available for 263 entries.
- **IMDb dataset updater:** configured for daily 00:00 Asia/Shanghai update and auto-apply.
- **Retired charts:** Douban real-time popular and high-rated charts are not current product features. Their collection endpoints were disallowed by robots.txt; collection was stopped and the UI entries removed.

See [Project status](docs/PROJECT-STATUS.md) for the verified production snapshot and [Development progress](docs/DEVELOPMENT-PROGRESS.md) for historical milestones. MovieHub is in maintenance mode; new collection sources or product features require a separate review.

## Features

- Browse imported chart definitions and date-stamped snapshots.
- View chart pagination, snapshot history, and rank changes between dates.
- Search the local catalogue by title/original title and filter by media type, year, rating, genres, and regions.
- View movie and TV details, available metadata, posters, and source identifiers.
- Discover additional titles through the TMDB-backed online discovery API.
- Keep local catalogue favorites and online-discovery favorites in one favorites experience. Favorite records remain stored by their respective backend mechanisms; deletion is linked across sources when a verified identity match exists.
- Open a configured Xiaoya search page for a title. MovieHub does not download or play media.
- Keep provider-specific source fields distinct. The current movie-rating display uses IMDb ratings; TMDB is used for metadata and discovery.

Availability depends on imported data and provider access. A chart definition alone is not evidence that a source has been collected or that a snapshot exists.

## Architecture

| Layer | Implementation |
|---|---|
| Frontend | React 18, TypeScript, Vite; served by Nginx |
| API | Python 3.10+, FastAPI, SQLAlchemy |
| Database | Application-owned SQLite database; explicit initialization and numbered migrations |
| Metadata | TMDB API, locally stored source-specific fields, and field-level provenance |
| IMDb ratings | Official IMDb non-commercial dataset workflow; separate rating columns and local index |
| Reverse proxy | Existing Nginx Proxy Manager (NPM) |
| Runtime | Docker Compose |

Compose defines three services:

- `moviehub`: FastAPI backend.
- `moviehub-web`: static frontend.
- `moviehub-imdb-updater`: optional scheduled IMDb dataset checker/updater. Its tracked configuration defaults to `enabled: false` and `auto_apply: false`; production scheduling/auto-apply is configured separately.

The frontend and API are reached through the existing NPM Docker network. Compose does not publish application ports to the NAS/LAN. The Synology deployment serves the UI below `/moviehub/`; the frontend build uses `MOVIEHUB_BASE_PATH` for that subpath.

## Data-source and licensing boundaries

- **Douban:** use only collection paths permitted by the source's published access rules. Collectors check robots.txt and stop on access-denied or rate-limit responses. The real-time popular and high-rated endpoints are retired and must not be run or reintroduced without a new source/permission review.
- **TMDB:** used for online discovery and selected metadata enrichment. Keep required attribution and the TMDB notice in the About/Credits page. The project is intended for non-commercial use; review the [TMDB terms and FAQ](https://developer.themoviedb.org/docs/faq) before changing usage.
- **IMDb:** the ratings dataset is subject to IMDb's personal, non-commercial-use restrictions. Keep the derived dataset, local index, database, and UI private to the individual user. Do not publish, redistribute, or expose IMDb-derived data as a public service. See [IMDb datasets](https://www.imdb.com/interfaces/) and [IMDb usage conditions](https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX).
- **Metadata provenance:** missing or ambiguous source values remain missing. Do not invent ratings, vote counts, identities, credits, or synopsis text.

## Quick start for development

### Backend

Python 3.10 or newer is required. From the repository root:

```sh
cd backend
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

To run the API locally, point it at a dedicated development data directory and initialize a **new local development database** explicitly before starting the server:

```sh
export MOVIEHUB_DATA_DIR="$PWD/.data"
export MOVIEHUB_BACKUP_DIR="$PWD/.backups"
mkdir -p "$MOVIEHUB_DATA_DIR" "$MOVIEHUB_BACKUP_DIR"
python -m scripts.init_db
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The initializer refuses to overwrite an existing non-empty database. Do not point local development commands at the production NAS database.

### Frontend

In a separate terminal:

```sh
cd frontend
npm install
npm test
MOVIEHUB_BASE_PATH=/moviehub/ npm run build
```

Browser E2E tests use Playwright Chromium:

```sh
npx playwright install chromium
npm run test:e2e
```

## Production deployment

Production deployment is intentionally not a one-command quick start. The application does not create or migrate its database on startup. Before any future deployment:

1. Read [Deployment](docs/DEPLOYMENT.md) and [Configuration](docs/CONFIGURATION.md).
2. Check the live schema version and pending migrations; the currently verified production schema is v5.
3. Run the read-only preflight from the project root: `python3 deploy/preflight.py`.
4. Follow the reviewed rollout procedure, including a verified backup and explicit migration step where required.
5. Verify `/api/health`, `/api/ready`, the UI route, and the expected proxy boundaries.

Do not initialize a production database over an existing one. Do not point MovieHub's database path at a Douban Scout database. NPM configuration changes and service restarts are separate operational actions and are not implied by a successful build.

Useful operator guides:

- [Deployment and NPM topology](docs/DEPLOYMENT.md)
- [Environment configuration and database lifecycle](docs/CONFIGURATION.md)
- [Database backup and restore](docs/BACKUP-RESTORE.md)
- [Chart import and validation](docs/CHART-IMPORT.md)
- [Chart source policy](docs/CHART-SOURCES.md)
- [IMDb ratings workflow and restrictions](docs/IMDB-RATINGS.md)
- [TMDB synopsis enrichment](docs/TMDB-OVERVIEWS.md)
- [TMDB API compliance](docs/TMDB-API-COMPLIANCE.md)

## Security and data-safety model

- The MovieHub SQLite database is independent of other applications.
- Database creation and schema migrations are explicit operator actions.
- The API and frontend containers run as non-root users with read-only root filesystems, dropped Linux capabilities, `no-new-privileges`, and resource/PID limits.
- The optional Scout import directory is mounted read-only and path/symlink boundaries are validated.
- Protected import and favorite operations require the configured API key. The favorites UI lets the operator enter the key and stores it in that browser's localStorage for subsequent same-origin API requests; do not use this on a shared/untrusted browser, and never commit the key or hard-code it into the shipped frontend bundle.
- Poster retrieval validates destinations and redirects to reduce SSRF risk, and validates response type/size before caching.
- Use the documented backup/restore utility rather than copying a live SQLite database file manually.

## Documentation index

- [Project status and delivery checklist](docs/PROJECT-STATUS.md)
- [Development progress history](docs/DEVELOPMENT-PROGRESS.md)
- [Original product scope and architecture baseline](docs/PRODUCT-SCOPE.md)
- [Database design](docs/phase4-database-design.md)
- [Chart snapshot import](docs/CHART-IMPORT.md)
- [Chart source policy](docs/CHART-SOURCES.md)
- [Official 2025 annual chart collector](docs/ANNUAL-CHART-COLLECTOR.md)
- [2025 annual chart artifact review](docs/ANNUAL-2025-ARTIFACT-REVIEW.md)
- [Scout import runbook](docs/SCOUT-IMPORT.md)
- [Read-only Scout chart coverage audit](docs/SCOUT-CHART-COVERAGE.md)
- [TMDB synopsis source research](docs/OVERVIEW-SOURCE-RESEARCH.md)
