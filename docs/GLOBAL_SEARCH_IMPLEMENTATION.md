# MovieHub Global Search & Discovery Implementation

## Product contract

MovieHub is a global movie and TV discovery, detail, and favorites application. It is not a user-maintained local library.
- Search covers TMDB movies and TV by default; local chart records may enrich/dedupe results but never constrain the result universe.
- No user-facing add-to-library or manual import flow for search results.
- Search pages, details, genres/countries, and poster bytes are cached on demand.
- Favorites are durable user-owned records independent of every cache TTL and eviction policy.
- Existing Douban charts and dated chart snapshots remain intact.
- TMDB IDs are always namespaced by media type (movie vs tv).
- Keep TMDB credentials server-side. Do not expose the bearer token to frontend assets or API responses.
- Do not persist bulk synopsis data until source terms, attribution, and redistribution permissions have been reviewed.

## Resource guardrails

Initial defaults (configurable, enforced server-side):

| Resource | Limit |
|---|---:|
| Search page size | 20 default, 40 hard maximum |
| Empty/whitespace search | No upstream search |
| Search response cache TTL | 15 minutes |
| Detail cache TTL | 7 days |
| Genre/country options TTL | 7 days |
| Poster cache TTL | 30 days |
| Negative search cache TTL | 2 minutes |
| TMDB concurrent requests | 4 |
| Poster download concurrent requests | 3 |
| Search cache capacity | Bounded by entry count and serialized bytes |
| Pagination | Fetch only the requested page; no eager page crawling |
| Retry | Bounded; never cache 429 or 5xx; respect Retry-After |
| Duplicate requests | Single-flight per normalized cache key |
| Cache cleanup | Expired-first then LRU; never touches favorites or chart snapshots |

The SQLite cache must use deterministic keys derived from provider, endpoint, normalized parameters, language, and region. Persist only the requested page. Cache cleanup must have a bounded work budget and must not hold a database connection while performing network I/O.

## Search and filtering

- /search/movie and /search/tv are combined for all search; allow movie-only and TV-only modes.
- /discover/movie and /discover/tv support genre, country, year, rating, and sort filters.
- Dynamic genre and country options come from TMDB endpoints and are cached.
- Multiple selections within one facet use OR semantics; different facets use AND semantics.
- Keep TMDB rating distinct from Douban rating; never merge their scales or vote counts.
- URL query parameters preserve the current filter state.
- Search results are lightweight; details are fetched only when opened.
- Local chart matches may be merged with external results by media_type + TMDB ID, without inserting every search hit into the movies table.

## Detail, posters, and favorites

- External detail route identity is provider + media_type + TMDB ID.
- Poster loading is lazy; do not download every result poster in advance.
- Reuse existing poster security controls and allowlisted image host policy.
- Favorites store media_type, TMDB ID, favorited_at, note, and a minimal display snapshot (title, release year, poster path, etc.) so favorites survive cache expiry and upstream outages.
- Migrate existing internal-movie favorites without loss; retain backward compatibility for chart-linked movies where practical.
- Cache eviction never deletes favorites, chart rows, or chart snapshots.

## Homepage discovery

Four separate discovery rails:
1. Horror: high-rated
2. Horror: hidden gems
3. Thriller: high-rated
4. Thriller: hidden gems

Use TMDB genre IDs Horror=27 and Thriller=53. Set bounded vote-count thresholds to avoid low-vote ranking distortion. Do not combine horror and thriller into one list.

## Delivery phases

1. Existing code/schema/API/frontend audit.
2. TMDB client, server-side token configuration, timeouts, concurrency and single-flight.
3. SQLite response cache, TTL, capacity accounting and bounded cleanup.
4. Global search, discover, genres/countries, details and poster path.
5. Durable TMDB-aware favorites migration and compatibility.
6. Frontend global search, multi-select filters, pagination, detail and favorites.
7. Horror/thriller homepage discovery rails.
8. Tests, CI, production backup/migration/deployment and live acceptance.

## Deployment safeguards

- Develop on feature/global-search-cache; do not push experiments directly to main.
- Production database changes require a backup, explicit migration, integrity_check and foreign_key_check.
- No automatic schema mutation on app startup.
- Do not restart Nginx Proxy Manager. Do not restart frontend or backend without a planned deployment and explicit user-facing notice.
- Preserve the NAS-local TMDB_API_READ_TOKEN Compose/.env wiring; never print the token.
- Report each completed phase with changed files, tests, CI status, remaining risks, and total progress.