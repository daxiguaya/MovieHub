# Scout coverage audit for chart snapshots

Before enriching or importing annual chart snapshots, MovieHub can compare their
Douban IDs with a consistent local copy of the Scout database. This audit opens
Scout SQLite with `mode=ro`, checks the expected schema, and reports ID match
rates, media-type mismatches and per-field metadata coverage. It never opens
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
URL, directors, actors, genres, regions and poster URLs. It also flags a
movie/TV type mismatch rather than silently treating it as valid metadata.

Use a consistent SQLite backup/copy with required WAL sidecars staged when
necessary. Do not point the audit at an actively changing database if a
consistent copy can be made. The tool does not copy the source database,
initialize MovieHub, start an import, or modify either database.

This is a preflight report only. The established Scout importer remains the
metadata ingestion path; chart import then fills only missing MovieHub fields.
A successful audit is not authorization to import or deploy.
