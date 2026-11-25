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

## Collect popular and high-rated snapshots atomically

The one-shot batch command refreshes both Douban tagged charts together. It collects both snapshots before creating a verified backup, then imports both through one all-or-nothing database transaction. If either collection is disallowed or fails, neither chart is written and no backup is created.

From the Synology production directory, run:

```sh
sh deploy/refresh_douban_tagged_charts.sh
```

An explicit snapshot date can be supplied:

```sh
sh deploy/refresh_douban_tagged_charts.sh 2026-11-25
```

The wrapper runs the backend command without restarting containers:

```sh
docker compose exec -T moviehub python -m scripts.refresh_douban_tagged_charts --date 2026-11-25 --max-items 100
```

The collector checks `robots.txt`, uses no cookies, proxy rotation, redirects or retries, and waits at least two seconds between pages while honoring any longer robots.txt crawl-delay. It stops on access denial, rate limiting, invalid JSON or duplicate IDs. This undocumented web-application endpoint is not an official public API; its response and availability can change. The endpoint provides list-level fields (ID, title, rating and cover), not full movie details.

The previous per-chart shell wrappers are retained for compatibility, but should not be used for routine refreshes: use the batch wrapper above so the two charts cannot become inconsistent.


## Import 2025 annual charts

The official Douban 2025 annual roundup identifies four separate film/TV lists. MovieHub has matching built-in chart slugs; keep each category in its own normalized snapshot:

| Chart slug | Official list |
| --- | --- |
| `annual-2025-chinese-movies` | 2025 评分最高华语电影 |
| `annual-2025-international-movies` | 2025 评分最高外语电影 |
| `annual-2025-hidden-gems` | 2025 年度冷门佳片 |
| `annual-2025-chinese-tv` | 2025 评分最高华语剧集 |

Source: [Douban official 2025 annual roundup](https://blog.douban.com/douban/2026/01/15/4382/).

The collector writes four files named `<chart-slug>-<capture-date>.json`. Keep all four files together in one directory and use the same actual capture date for all four. The batch CLI validates the complete set before opening the database. It checks file presence, declared slug, source (`douban`), category (`annual`), period (`2025`), snapshot date, built-in movie/TV type, schema constraints, unique IDs/ranks and ascending rank order. It does not fetch the official page or invent missing movie metadata.

Run from the backend directory. Validation-only is the default and does not inspect or open the database:

```bash
python -m scripts.import_annual_charts \\
  --input-dir /imports/annual-2025 \\
  --date 2026-11-23
```

After reviewing the preflight summary and confirming the four files are the intended normalized source data, explicitly apply all four in one all-or-nothing database transaction:

```bash
python -m scripts.import_annual_charts \\
  --input-dir /imports/annual-2025 \\
  --date 2026-11-23 \\
  --apply
```

If any chart fails validation or import, the batch is rejected; a database import failure rolls back all four charts together. This is a separate manual operation from collection and does not run automatically in CI or against the Scout database.

The four categories must remain separate: Chinese films, international films, hidden gems and Chinese TV series are not one comparable ranking. The annual collector has been run successfully in CI: four normalized snapshots (8/10/10/10 entries) passed dry-run validation and were uploaded as a 14-day GitHub Actions artifact. The JSON is not committed to Git and has not been imported into any database. As of the 2026-11-23 review, the 2026 annual categories and ranking data had not been verified; no empty 2026 placeholder is seeded. Add 2026 definitions only after official publication.

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

The import validates unique Douban IDs and ranks. For built-in chart slugs it also checks the declared category and period, and rejects movie/TV entries that do not match that chart's media type. These checks run during local JSON validation, before the CLI checks or opens the MovieHub database. Custom operator-defined slugs retain the generic schema. It uses Douban IDs only as external matching keys; all MovieHub chart relationships are written with MovieHub's internal `movies.id`.

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
