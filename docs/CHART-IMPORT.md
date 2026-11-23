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

This is a safe, repeatable persistence/import workflow, not an automated chart collector. Douban Top 250, real-time popular, high-rated and annual chart acquisition/update scheduling remain separate work. Do not treat seeded chart definitions as proof that chart data has been collected.

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
