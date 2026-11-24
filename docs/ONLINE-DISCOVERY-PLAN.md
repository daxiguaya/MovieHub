# MovieHub Online Discovery — Scope and Progress

Last updated: 2026-11-24

## Product decision

MovieHub is an online-first movie and TV discovery experience. Search covers the upstream catalog; users do not manually add titles to a local movie library. Search and detail data are cached automatically. Favorites are durable user data.

## Product requirements

1. Search movies and TV shows online, not only the locally imported chart records.
2. Search local chart records alongside online results and deduplicate by provider identity where possible.
3. Support keyword search, movie/TV selection, genre, region, year, rating, and pagination.
4. Genre and region choices are loaded from backend provider data and presented as multi-select controls.
5. Fetch full details only when a user opens a title; do not fan out detail calls for search result pages.
6. Keep Douban chart data and ratings distinct from TMDB discovery data and ratings.
7. Keep TMDB credentials server-side and provide required attribution.
8. Do not persist overview/synopsis fields until source terms and display requirements have been checked.

## Performance and resource guardrails

- Search page size: 20 results (TMDB page size); only the requested page is fetched.
- Fetch the next page only after the user explicitly clicks to load more; no speculative prefetch.
- Empty/too-short keyword searches do not trigger broad catalog scans.
- Persistent SQLite cache, no Redis or additional always-on service.
- Initial TTLs: search/Discover 15 minutes; detail 7 days; genre/region metadata 7 days; negative search 2 minutes.
- Cache limits: 1,500 entries, 32 MiB serialized-response budget, 1 MiB per entry; expired entries first, then LRU.
- SQLite uses incremental auto-vacuum and compacts when database plus WAL footprint exceeds its threshold.
- Do not cache 429, 5xx, timeouts, or malformed upstream responses.
- Merge identical concurrent upstream requests; cap upstream concurrency at four; 8-second timeout and 2 MiB response limit; no automatic retry loop.
- Stale cache may be served during upstream outages when safe.
- Cache eviction must never delete favorites, chart snapshots, or required favorite display snapshots.
- Search responses contain lightweight fields only. Detail and poster requests are on demand.
- Cache stats expose entries/bytes/hits/misses/stale hits/writes and upstream latency/failure/rate-limit counters.

## Favorites

- No user-facing “add to library” operation.
- Favorite identity is provider + media type + provider ID (not a bare integer).
- Keep favorite relation durable and retain a small display snapshot (title, year, poster path) so cache expiry or upstream downtime cannot blank the favorites page.
- Full metadata remains independently refreshable/evictable.
- Favorites API key is entered locally and stored only in the current browser tab's sessionStorage.

## Horror and thriller discovery

- Place horror/thriller discovery prominently near the top of the home page.
- Maintain four distinct discovery lists: horror high-score, horror hidden gems, thriller high-score, thriller hidden gems.
- Use TMDB Discover with vote-count thresholds and bounded pagination/cache refresh; never crawl the entire genre catalog.
- Keep horror and thriller separate.

## Delivery phases and acceptance

| Phase | Scope | Status |
|---|---|---|
| 0 | Product decisions, resource guardrails, and delivery plan | Complete |
| 1 | Persistent bounded provider-response cache and TMDB client | Complete |
| 2 | Online search/Discover/detail/genre-region APIs and backend tests | Complete |
| 3 | Frontend online search, dynamic multi-select filters, detail pages, favorites, and pagination | Complete |
| 4 | Prominent horror/thriller homepage spotlight and four dedicated paginated lists | Complete |
| 5 | Attribution, operational metrics, resource/load tests, and NAS acceptance | In progress: code and CI complete; NAS backup/restore and real-load acceptance pending |

## Implementation notes (2026-11-24)

- PR #10: https://github.com/daxiguaya/MovieHub/pull/10
- PR #10 was squash-merged into main as commit `4bb563476bf5b6518cf72fe831091fe9f2a8fcb2`.
- Final CI run `45428916856` passed backend tests, frontend tests/build, Compose smoke, and browser E2E (12 browser tests).
- Online favorites are stored separately from the evictable response-cache table in the discovery SQLite file. Cache eviction never removes them.
- The discovery DB is backed up with SQLite's online backup API once per day (7-day retention); the daily snapshot is refreshed immediately after favorite add/remove.
- The protected favorites flow accepts a user-entered API key in the Favorites page and stores it only in the current browser tab's sessionStorage. The key is sent only to the same-origin MovieHub API, never to TMDB.
- A dedicated About/Credits page includes a TMDB-hosted logo asset and the required notice, following TMDB's official FAQ: https://developer.themoviedb.org/docs/faq. The selected logo variant still needs final confirmation against the current approved asset list.
- The cache stats endpoint reports entries, serialized bytes, database bytes, WAL bytes, hits, misses, stale hits, writes, TMDB upstream attempts, successes, failures, 429s, and average/maximum latency.
- TMDB `overview` is recursively stripped from provider responses before caching; synopsis text remains absent from local storage until compliance is cleared.
- No production deployment or service restart has been performed by this work.

## Remaining before production rollout

1. Verify the protected favorites API key flow through the actual NPM path.
2. Confirm the discovery backup/restore procedure on the NAS.
3. Observe cache size, hit rate, upstream latency, and container memory under real use.
4. Confirm the selected TMDB logo asset is one of the currently approved variants.
5. Deploy backend and frontend deliberately after the NAS acceptance checks; do not restart NPM or unrelated services.
6. Keep synopsis import disabled until source compliance is resolved.

## Deployment constraints

- Do not restart Nginx Proxy Manager or unrelated services during deployment.
- Preserve the existing production database and its 288 chart records.
- No production synopsis import without a separate compliance decision.
