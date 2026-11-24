# Phase 4 — MovieHub database foundation

Status: design baseline for the independent MovieHub database.
Target: a new, empty SQLite database owned by MovieHub. Douban Scout is an external, read-only import source and is never migrated or modified by MovieHub.

## Goals

- MovieHub can initialize its own database from an empty file.
- Internal relationships use MovieHub's integer `movies.id`, never an external provider ID.
- Douban, IMDb and TMDb identifiers remain nullable external identifiers.
- A chart definition and each dated chart snapshot are separate records.
- Re-importing one chart/date replaces only that snapshot.
- Existing snapshots on other dates and other charts remain unchanged.
- Chart imports may create missing movie records, but must not overwrite populated metadata fields.
- No production database is created or migrated during this phase.

## Tables

There are 11 core tables:

1. `movies`
2. `genres`
3. `regions`
4. `movie_genres`
5. `movie_regions`
6. `movie_posters`
7. `lists`
8. `chart_snapshots`
9. `list_items`
10. `favorites`
11. `schema_migrations`

### movies

- `id INTEGER PRIMARY KEY`: MovieHub internal identity.
- `douban_id TEXT NULL UNIQUE`, `imdb_id TEXT NULL UNIQUE`, `tmdb_id TEXT NULL UNIQUE`: external identifiers; none is the internal key.
- Existing metadata fields remain: `title`, `original_title`, `year`, `rating`, `rating_count`, `type`, `directors`, `actors`, `overview`, `douban_url`, `updated_at`.
- `title` is required. `type` is constrained to `movie` or `tv`. Rating is 0–10 and rating_count is non-negative.
- Unique indexes on nullable external IDs permit multiple NULLs in SQLite while preventing duplicate non-NULL IDs.

### genres / regions and associations

- `genres(id, name)` and `regions(id, name)`; names are unique.
- `movie_genres(movie_id, genre_id)` and `movie_regions(movie_id, region_id)` use composite primary keys.
- Association foreign keys reference internal IDs and use ON DELETE CASCADE.
- `movie_posters(movie_id, url)` uses a composite primary key and references `movies.id` with ON DELETE CASCADE.

### lists

Keeps the existing chart definition fields: `list_id`, `slug`, `name`, `source`, `category`, `period`, `description`, `enabled`, `display_order`, `last_updated`, `created_at`, `updated_at`.

- `slug` is unique.
- timestamps are non-null where ORM defaults exist; `last_updated` is nullable.
- Deleting a list cascades to its snapshots and items.

### chart_snapshots

- `id INTEGER PRIMARY KEY`
- `list_id INTEGER NOT NULL` references `lists.list_id` ON DELETE CASCADE
- `snapshot_date TEXT NOT NULL` in ISO `YYYY-MM-DD` format
- `imported_at TEXT NOT NULL`
- `item_count INTEGER NOT NULL` and non-negative
- `UNIQUE(list_id, snapshot_date)`

A snapshot is a first-class record. A successful import stores its metadata and all items atomically. Empty snapshots are not accepted by the current API contract; the table design does not require a fake item row.

### list_items

- `snapshot_id INTEGER NOT NULL` references `chart_snapshots.id` ON DELETE CASCADE
- `movie_id INTEGER NOT NULL` references `movies.id` ON DELETE RESTRICT
- `rank INTEGER NOT NULL` and positive
- `source_rating REAL NULL` constrained to 0–10 when present
- primary key `(snapshot_id, movie_id)`
- unique `(snapshot_id, rank)`
- index on `(snapshot_id, rank)`

The snapshot date is obtained through `chart_snapshots`; it is not duplicated in each item.

### favorites

- `movie_id INTEGER PRIMARY KEY` references `movies.id` ON DELETE RESTRICT
- `created_at TEXT NOT NULL`
- `note TEXT NOT NULL DEFAULT ''`

Single-user self-hosted scope for now; no user/account table is introduced.

### schema_migrations

Tracks `version`, `name`, and `applied_at`. Version 1 is the first MovieHub-owned schema, not an in-place Scout schema alteration.

## Data ownership and merge policy

### Douban Scout import

Scout is opened read-only. It is the authoritative source for the fields it supplies: title, type, year, rating, rating count, original title, directors, actors, overview, Douban URL, genres, regions and poster URLs. Missing source values do not erase existing MovieHub values. Existing genre/region associations are replaced only when Scout supplies a non-empty authoritative list. Poster URLs are additive.

### Chart import

Chart imports own chart metadata, snapshot date, rank and `source_rating`. They can create a movie that does not yet exist, identified by Douban ID. For an existing movie, chart data only fills empty metadata fields; it must not replace populated Scout metadata. Genre/region associations are only filled when the movie currently has none. Poster URLs are additive.

### Identity

- Current import payloads identify records by Douban ID.
- Resolve the external Douban ID to `movies.id` once, then store only `movie_id` in internal relationships.
- Future non-Douban ingestion must resolve by another external identifier or an explicit matching process; it must not invent a Douban ID.

## Initialization and migration behavior

- `backend/migrations/001_moviehub_core.sql` creates the entire schema from an empty SQLite database. It must not ALTER or assume any Scout table.
- A dedicated `python -m scripts.init_db` command initializes a new MovieHub database and runs structural/integrity validation.
- Application module import and FastAPI startup must not create tables or silently initialize a database.
- SQLite WAL mode is enabled by the explicit initializer, not as an import-time side effect.
- The initializer refuses to overwrite a non-empty unrecognized database. No automatic conversion of a Scout database is supported.
- ORM metadata and SQL schema must be tested for table names, columns, nullability, primary keys, unique constraints, foreign keys, indexes and delete actions.

## Required tests before merging

1. Initialize a brand-new temporary SQLite database from the SQL migration.
2. Verify all 11 tables, indexes, constraints and foreign keys.
3. Compare SQL schema with SQLAlchemy ORM metadata.
4. Import a Scout-shaped fixture read-only and verify internal IDs/associations.
5. Import a chart with new and existing Douban IDs.
6. Re-import the same chart/date and verify only that snapshot is replaced.
7. Import another date and verify the earlier snapshot remains unchanged.
8. Verify chart import does not overwrite populated movie metadata.
9. Verify deleting a movie referenced by a chart item or favorite is restricted.
10. Run SQLite integrity and foreign-key checks.

No production data migration, deployment or service restart is part of Phase 4.
