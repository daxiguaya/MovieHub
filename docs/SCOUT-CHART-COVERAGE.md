# Scout coverage audit for chart snapshots

Before enriching or importing annual chart snapshots, MovieHub can compare their
Douban IDs with a consistent local copy of the Scout database. This audit opens
Scout SQLite with `mode=ro`, checks the expected schema, and reports ID match
rates, media-type mismatches and per-field metadata coverage. ID matches with
the wrong media type remain visible as ID matches and mismatches, but are
excluded from the valid-match denominator and all metadata field-coverage
numerators. It never opens
the MovieHub database and never writes to Scout.

Run from the backend directory:

```sh
python -m scripts.audit_chart_scout_coverage \
  --scout-db /imports/scout-readonly.sqlite \
  --input /tmp/moviehub-annual-2025/annual-2025-chinese-movies-2026-11-23.json \
  --input /tmp/moviehub-annual-2025/annual-2025-international-movies-2026-11-23.json \
  --input /tmp/moviehub-annual-2025/annual-2025-hidden-gems-2026-11-23.json \
  --input /tmp/moviehub-annual-2025/annual-2025-chinese-tv-2026-11-23.json
```

The report shows how many chart entries have Scout matches and how many matched
records contain year, rating, rating count, original title, overview, Douban
URL, directors, actors, genres, regions and poster URLs. It includes both
per-chart and aggregate field-coverage counts/percentages, using only unique
Scout matches with the expected media type as the denominator. Duplicate
chart/date inputs are rejected before the Scout database is opened. It also
flags a movie/TV type mismatch rather than silently treating it as valid metadata.
If Scout contains more than one row for the same Douban ID, the audit reports
that ID as ambiguous and excludes it from field-coverage calculations rather
than selecting an arbitrary row. Unexpected Scout media types are included in
the ID lookup so they are reported as mismatches, not incorrectly counted as
missing.

Use a consistent SQLite backup/copy with required WAL sidecars staged when
necessary. Do not point the audit at an actively changing database if a
consistent copy can be made. The tool does not copy the source database,
initialize MovieHub, start an import, or modify either database.

This is a preflight report only. The established Scout importer remains the
metadata ingestion path; chart import then fills only missing MovieHub fields.
A successful audit is not authorization to import or deploy.
