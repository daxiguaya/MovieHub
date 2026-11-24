# MovieHub Online Discovery — Scope and Progress

Last updated: 2026-11-24

## Product decision

MovieHub is an online-first movie and TV discovery experience. Search covers the upstream catalog; users do not manually add titles to a local movie library. Search and detail data are cached automatically. Favorites are durable user data.

## Product requirements

1. Search movies and TV shows online, not only the locally imported chart records.
2. Search local chart records alongside online results and deduplicate by provider identity where possible.
3. Support keyword search, movie/TV selection, genre, region, year, rating, sorting, and pagination.
4. Genre and region choices are loaded from backend provider data and presented as multi-select controls.
5. Fetch full details only when a user opens a title; do not fan out detail calls for search result pages.
6. Keep Douban chart data and ratings distinct from TMDB discovery data and ratings.
7. Keep TMDB credentials server-side and provide required attribution.
8. Do not bulk import overview/synopsis fields until source terms and display requirements have been checked.

## Performance and resource guardrails

- Search page default: 20; hard maximum: 40.
- Fetch the next page only after explicit user pagination/scroll demand; no speculative page prefetch.
- Normalize and validate query parameters; empty/too-short queries do not trigger broad catalog scans.
- Persistent SQLite cache, no Redis or additional always-on service.
- Initial TTLs: search 15 minutes; detail 7 days; genre/region metadata 7 days; negative search 2 minutes.
- Bound cache by both row count and serialized bytes; evict expired entries first, then least-recently-used entries.
- Do not cache 429, 5xx, timeouts, or malformed upstream responses.
- Merge identical concurrent upstream requests; cap upstream and poster concurrency; bounded timeouts/retries.
- Stale cache may be served during upstream outages when safe.
- Cache eviction must never delete favorites, chart snapshots, or required favorite display snapshots.
- Search responses contain lightweight fields only. Detail and poster requests are on demand.
- Add observable cache size/hit/miss/upstream latency/rate-limit metrics.

## Favorites

- Remove the concept of a user-facing “add to library” operation.
- Favorite identity is provider + media type + provider ID (not a bare integer).
- Keep favorite relation durable and retain a small display snapshot (title, year, poster path) so cache expiry or upstream downtime cannot blank the favorites page.
- Full metadata remains independently refreshable/evictable.

## Horror and thriller discovery

- Place horror/thriller discovery prominently near the top of the home page.
- Maintain four distinct discovery lists: horror high-score, horror hidden gems, thriller high-score, thriller hidden gems.
- Use provider Discover with vote-count thresholds and bounded pagination/cache refresh; never crawl the entire genre catalog.
- Keep horror and thriller separate; allow users to combine them in ordinary filters if desired.

## Delivery phases and acceptance

| Phase | Scope | Status |
|---|---|---|
| 0 | Product decisions, resource guardrails, and delivery plan | Complete |
| 1 | Persistent bounded provider-response cache and TMDB client | Complete (backend unit/API tests passed; final CI rerun pending) |
| 2 | Online search/discover/details/genre-region APIs and backend tests | Complete (backend tests passed; final CI rerun pending) |
| 3 | Frontend online search, multi-select filters, paging, cancellation | Pending |
| 4 | Prominent horror/thriller sections and four curated lists | In progress (homepage spotlight plus four dedicated paginated lists implemented; final browser/API acceptance pending) |
| 5 | Attribution, operational metrics, resource/load tests, full acceptance | Pending |

## Implementation notes (2026-11-24)\n\n- PR #10: https://github.com/daxiguaya/MovieHub/pull/10\n- Backend CI completed successfully on the earlier PR revision; frontend type-check and one legacy UI test failed on that revision. Fixes were committed afterward; a fresh complete CI run is required before merge.\n- Online favorites are stored separately from the evictable response-cache table in the discovery SQLite file. Cache eviction never removes them. The discovery DB is backed up with SQLite backup API once per day (7-day retention), and the daily snapshot is refreshed immediately after a favorite add/remove.\n- The protected favorites flow now accepts a user-entered API key in the Favorites page and stores it only in the current browser tab sessionStorage; the key is sent only to the same-origin MovieHub API, never to TMDB.\n- Latest completed browser E2E run passed after correcting the Discover filter test to assert the actual online Discover request. A new run is required for the later stable-ID deduplication, credits, and tab-session favorites authentication changes.
- Added a dedicated About/Credits page with an unmodified TMDB-hosted logo asset and the required notice, following TMDB's official FAQ: https://developer.themoviedb.org/docs/faq.\n\n## Deployment constraints

- Do not restart Nginx Proxy Manager or the frontend during backend-only changes.
- Do not deploy to the NAS production directory until CI and review pass.
- Preserve the existing production database and its 288 chart records.
- No production synopsis import without a separate compliance decision.
