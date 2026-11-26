# Future annual chart imports

The 2025 collector and four-chart importer are intentionally preserved as a
source-specific historical workflow. Do not repurpose their fixed slugs or
period. For a later Douban annual release (for example, period `2026`), use
the manifest-driven importer below.

## 1. Prepare normalized snapshots

After the official annual roundup is published, first review its actual
source page and current `robots.txt`. Build or update a source-specific
collector only for the published structure and only when access is permitted.
Do not guess endpoints, scrape blocked paths, rotate proxies, simulate a
browser, or retry 403/429 responses.

The collector should emit one normalized JSON file per chart, named:

```
annual-2026-chinese-movies-YYYY-MM-DD.json
annual-2026-international-movies-YYYY-MM-DD.json
annual-2026-chinese-tv-YYYY-MM-DD.json
```

The filenames use the actual capture date; each JSON `period` is the annual
ranking year. The chart set and media types must reflect the real official
release—these example names are not a prediction of the 2026 release.

## 2. Declare the year-specific chart set

Create a manifest next to the JSON files:

```json
{
  "period": "2026",
  "charts": [
    {
      "slug": "annual-2026-chinese-movies",
      "name": "2026 评分最高华语电影",
      "media_type": "movie"
    },
    {
      "slug": "annual-2026-international-movies",
      "name": "2026 评分最高外语电影",
      "media_type": "movie"
    },
    {
      "slug": "annual-2026-chinese-tv",
      "name": "2026 评分最高华语剧集",
      "media_type": "tv"
    }
  ]
}
```

Only declare charts actually present in the official release. Every slug must
begin with `annual-<period>`, preventing a 2026 batch from targeting 2025
chart identities. Each snapshot must carry `source=douban`,
`category=annual`, the same `period` and capture date, and the declared
media type.

## 3. Validate, then import

Run from the backend working directory. Dry-run is the default and does not
open the database:

```sh
python -m scripts.import_annual_snapshot_batch \
  --input-dir /imports/annual-2026 \
  --manifest /imports/annual-2026/manifest.json \
  --date YYYY-MM-DD
```

Review the complete chart/item summary. Only then explicitly write:

```sh
python -m scripts.import_annual_snapshot_batch \
  --input-dir /imports/annual-2026 \
  --manifest /imports/annual-2026/manifest.json \
  --date YYYY-MM-DD \
  --apply
```

The declared batch is imported through the existing all-or-nothing
`ChartImportService.import_snapshots()` transaction. The same chart and
snapshot date may be re-imported (that exact snapshot is replaced); other
snapshot dates, other chart slugs, and 2025 history remain untouched. Existing
chart enabled/display-order settings are preserved.

## Boundaries

- This generic importer does not scrape Douban and does not invent a 2026
  collector before the official source exists.
- 2025 collector/importer remain unchanged and reproducible.
- The TMDB metadata enrichment and Douban rating-count enrichment remain
  separate, opt-in, dry-run-first steps; neither changes the chart's original
  Douban rank or source rating.
- A denied/rate-limited source or disallowed robots path means stop collection;
  existing local snapshots remain available.
