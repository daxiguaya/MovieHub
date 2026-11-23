# Chart snapshot import

MovieHub separates chart acquisition from chart persistence. The backend accepts a normalized JSON snapshot and stores it in the independent MovieHub database. It does not scrape Douban or fetch data from Cinephile.

## Supported local import

From the backend directory, validate a snapshot without writing:

```bash
python -m scripts.import_chart --input /imports/charts/top250-2026-11-23.json --dry-run
```

Import after the MovieHub database has been explicitly initialized:

```bash
python -m scripts.import_chart --input /imports/charts/top250-2026-11-23.json
```

For a local export prepared from Cinephile, select the adapter:

```bash
python -m scripts.import_chart --input /imports/charts/cinephile-top250.json --adapter cinephile --dry-run
python -m scripts.import_chart --input /imports/charts/cinephile-top250.json --adapter cinephile
```

The Cinephile adapter accepts an already normalized MovieHub snapshot. It does not scrape, clone, or execute Cinephile code.

## Collect a fresh Douban Top 250 snapshot

The repository includes a one-shot public-page collector. It checks `robots.txt`, requests the ten Top 250 pages sequentially with at least a two-second delay, disables redirects, uses no cookies or proxy rotation, and stops on access denial or HTTP 429. It does not bypass login, challenges or rate limits.

Run inside the backend container (write to `/tmp`, because the Scout import mount is read-only):

```sh
docker compose exec moviehub python -m scripts.collect_douban_top250 \
  --date 2026-11-23 \
  --output /tmp/moviehub-top250-2026-11-23.json
```

Validate and then import into the independent MovieHub database:

```sh
docker compose exec moviehub python -m scripts.import_chart \
  --input /tmp/moviehub-top250-2026-11-23.json --dry-run

docker compose exec moviehub python -m scripts.import_chart \
  --input /tmp/moviehub-top250-2026-11-23.json
```

If robots.txt disallows the path, Douban returns 403/429, a redirect occurs, or page markup/ranks are incomplete, collection stops without producing a partial snapshot. Do not work around those restrictions. The collector has no scheduler and is not run automatically.

## Collect popular and high-rated snapshots

A second one-shot collector uses Douban's web-application `/j/search_subjects` JSON endpoint for the `热门` and `豆瓣高分` tags. This is an undocumented web endpoint, not an official public API; its response and availability can change.

Collect up to 100 popular movies:

```sh
docker compose exec moviehub python -m scripts.collect_douban_tagged_chart \
  --chart popular \
  --date 2026-11-23 \
  --output /tmp/moviehub-popular-2026-11-23.json
```

Collect up to 100 high-rated movies:

```sh
docker compose exec moviehub python -m scripts.collect_douban_tagged_chart \
  --chart high-rated \
  --date 2026-11-23 \
  --output /tmp/moviehub-high-rated-2026-11-23.json
```

The collector checks `robots.txt`, uses no cookies, proxy rotation, redirects or retries, and waits at least two seconds between pages and honors any longer robots.txt crawl-delay. It stops on access denial, rate limiting, invalid JSON or duplicate IDs. The endpoint provides only list-level fields (ID, title, rating and cover); run the read-only Scout metadata import as needed to enrich year, rating count, genres, regions and details.

Then use the same `import_chart --dry-run` and import commands above. Annual charts are not covered by this collector yet.


## Import 2025 annual charts

The official Douban 2025 annual roundup identifies four separate film/TV lists. MovieHub has matching built-in chart slugs; keep each category in its own normalized snapshot:

| Chart slug | Official list |
| --- | --- |
| `annual-2025-chinese-movies` | 2025 评分最高华语电影 |
| `annual-2025-international-movies` | 2025 评分最高外语电影 |
| `annual-2025-hidden-gems` | 2025 年度冷门佳片 |
| `annual-2025-chinese-tv` | 2025 评分最高华语剧集 |

Source: [Douban official 2025 annual roundup](https://blog.douban.com/douban/2026/01/15/4382/).

Prepare one JSON file per list using the same [snapshot format](#snapshot-format), with `source: "douban"`, `category: "annual"`, and the matching slug/name above. Use the actual date on which the source list was captured as `snapshot_date`; the `period` is already part of each built-in chart definition. Validate each file with `--dry-run` before importing. The normalized import path does not fetch the official page or invent missing movie metadata.

The four categories must remain separate: Chinese films, international films, hidden gems and Chinese TV series are not one comparable ranking. MovieHub does not bundle the annual list dataset in Git. As of the 2026-11-23 review, the 2026 annual categories and ranking data had not been verified; no empty 2026 placeholder is seeded. Add 2026 definitions only after official publication.

## Snapshot format

The file must be UTF-8 JSON and conform to `ChartSnapshotImport`. Minimal example:

```json
{
  "slug": "top250",
  "name": "豆瓣电影 Top 250",
  "source": "douban",
  "category": "classic",
  "snapshot_date": "2026-11-23",
  "movies": [
    {
      "douban_id": "1292052",
      "rank": 1,
      "source_rating": 9.7,
      "title": "肖申克的救赎",
      "year": 1994,
      "rating": 9.7,
      "type": "movie",
      "genres": ["剧情"],
      "regions": ["美国"],
      "posters": ["https://img1.doubanio.com/view/photo/l/public/example.jpg"]
    }
  ]
}
```

The import validates unique Douban IDs and ranks. It uses Douban IDs only as external matching keys; all MovieHub chart relationships are written with MovieHub's internal `movies.id`.

## Replacement and history behavior

- Re-importing the same chart slug and date replaces only that snapshot.
- Other dates and other charts remain untouched.
- Chart-provided metadata fills missing movie fields and does not overwrite populated Scout metadata.
- Poster URLs are additive.
- An empty or invalid snapshot is rejected before existing snapshot data is changed.
- The CLI writes only to the configured MovieHub database. It never opens the Scout database.

## Acquisition status

This is a safe, repeatable persistence/import workflow, not an automated chart collector. Douban Top 250, real-time popular and high-rated have opt-in one-shot collectors. The 2025 annual categories have built-in definitions but require separate validated normalized data imports; annual collection and update scheduling remain unimplemented. Do not treat seeded chart definitions as proof that chart data has been collected.

## Historical rank comparison

When at least two snapshots exist for a chart, the API can compare them:

```http
GET /api/charts/{slug}/compare?from_date=2026-11-22&to_date=2026-11-23
```

The result matches entries by MovieHub's internal `movie_id` and reports:

- `before_rank` and `after_rank`
- `rank_change`: positive means the movie moved up; negative means it moved down
- `new`, `removed`, `moved` and `unchanged` status

The chart detail page exposes the same comparison with date selectors. A missing snapshot returns 404; comparing a date with itself returns 400.
