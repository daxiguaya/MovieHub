# Official 2025 annual chart collection

MovieHub can collect the four 2025 film/TV lists from Douban's official annual
roundup article:

- Source article: https://blog.douban.com/douban/2026/01/15/4382/
- Capture source: official Douban blog HTML, not a guessed tag search or a
  third-party ranking dump.
- The collector checks `blog.douban.com/robots.txt` before requesting the
  article and fails closed if robots.txt cannot be read or disallows the path.
- It uses no login, cookies, proxy rotation, retries, redirect following or
  challenge bypass. HTTP 401/403/429 stops collection.
- One article fetch produces four separate normalized JSON files. It does not
  open the MovieHub database.

## Run

From the backend container or backend working directory:

```sh
python -m scripts.collect_douban_annual \
  --date 2026-11-23 \
  --output-dir /tmp/moviehub-annual-2025
```

The date is the actual local capture date, not the annual period. The period
remains `2025` in each built-in chart definition.

Expected output files:

- `annual-2025-chinese-movies-2026-11-23.json`
- `annual-2025-international-movies-2026-11-23.json`
- `annual-2025-hidden-gems-2026-11-23.json`
- `annual-2025-chinese-tv-2026-11-23.json`

The official article currently lists 8 linked Chinese-film entries (ranks 9
and 10 are explicitly marked empty), 10 international films, 10 hidden gems
and 10 Chinese TV series. Empty positions are not invented or renumbered.

## Validate and optionally import the complete batch

From the backend working directory, validate all four files together. The
default command is a dry run: it checks the complete set, chart identity,
source/category/period, capture date, media type, schema constraints, IDs and
rank ordering without checking or opening the database.

```sh
python -m scripts.import_annual_charts \
  --input-dir /tmp/moviehub-annual-2025 \
  --date 2026-11-23
```

After reviewing the summary and confirming the files are the intended source
data, explicitly import all four in one all-or-nothing database transaction:

```sh
python -m scripts.import_annual_charts \
  --input-dir /tmp/moviehub-annual-2025 \
  --date 2026-11-23 \
  --apply
```

A missing/invalid file prevents database access. A database error during apply
rolls back the whole four-chart batch. The collector itself never imports,
never seeds the database and never touches Scout.

The article supplies title, rank, director, rating and Douban subject ID.
Year, genres, regions, poster URLs and other metadata are intentionally left
empty rather than fabricated; the existing read-only Scout import can enrich
missing metadata later. TV rows are typed as `tv`; the three film lists are
typed as `movie`.

This collector is a manual, one-shot adapter for an undocumented page layout,
not a scheduled scraper or a supported Douban API. If robots.txt or page
markup changes, it stops and requires review. Do not bypass access controls.


## Production status

The four 2025 annual lists described here have since been imported into the production MovieHub database and confirmed by the production audit: four snapshots and 38 entries total (8/10/10/10). This runbook remains for reproducible manual collection/validation when needed; it does not imply that scheduled collection is enabled or that a new import should be performed. Do not re-import into production without a separate backup, preflight, and explicit operational decision.
