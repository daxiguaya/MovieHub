# IMDb ratings (personal, non-commercial use only)

MovieHub keeps IMDb ratings in dedicated `imdb_rating` and
`imdb_rating_count` columns. The existing `rating` and `rating_count`
columns remain unchanged for Douban-origin data and historical chart records.
TMDB ratings remain provider metadata and must never be copied into IMDb fields.

## Official source and terms

Use only IMDb's official non-commercial dataset:

- `https://datasets.imdbws.com/title.ratings.tsv.gz`
- Dataset description: `https://www.imdb.com/interfaces/`
- Usage conditions: `https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX`

IMDb states that these datasets are for personal, non-commercial use, may not
be scraped from the website, and must not be republished/resold/repurposed to
create a database except for individual personal use. Keep the dataset,
MovieHub database and UI private to the individual user. Do not publish or
share the IMDb-derived database, dataset file, or public service. Re-check
IMDb's terms before each future use; permission may be withdrawn.

Required attribution in the product:

> Information courtesy of IMDb (https://www.imdb.com). Used with permission.

## Schema and migration

Schema v5 adds nullable `movies.imdb_rating` and
`movies.imdb_rating_count`. Migration 005 does not rewrite or copy the
existing Douban fields, chart `source_rating`, rankings, snapshots, favorites,
or metadata.

Run the standard migration after pulling the code:

```sh
cd /volume1/docker/moviehub && docker compose build moviehub
cd /volume1/docker/moviehub && docker compose run --rm --no-deps moviehub python -m scripts.migrate
```

The migration runner creates and verifies a SQLite online backup before
applying the numbered migration, then validates integrity, foreign keys and
the ORM schema. Do not manually alter the production database.

After the migration succeeds, deploy the API and UI code with:

```sh
cd /volume1/docker/moviehub && docker compose up -d --build moviehub moviehub-web
```

No Nginx Proxy Manager restart is required.

## Import ratings

Download the official file directly from IMDb into the host directory configured by
Compose's `MOVIEHUB_IMPORT_PATH` (mounted read-only at `/imports` in the backend
container). If that variable points to the existing NAS `import-staging` folder,
place the file there. Do not commit or upload the dataset to GitHub.

Example:

```sh
curl -fL https://datasets.imdbws.com/title.ratings.tsv.gz -o /volume1/docker/moviehub/import-staging/title.ratings.tsv.gz
```

After schema v5 is active, run a dry-run first:

```sh
cd /volume1/docker/moviehub && docker compose run --rm --no-deps moviehub python -m scripts.import_imdb_ratings --input /imports/title.ratings.tsv.gz
```

Only exact, already stored IMDb title IDs (`tt...`) are eligible. No title
fuzzy matching or automatic IMDb ID assignment occurs. The importer streams
the gzip TSV, validates ratings/vote counts, rejects duplicate matching IDs,
and reports coverage. It does not clear an existing IMDb rating when an ID is
absent from the dataset. It never changes Douban ratings.

After reviewing the dry-run summary, explicitly apply:

```sh
cd /volume1/docker/moviehub && docker compose run --rm --no-deps moviehub python -m scripts.import_imdb_ratings --input /data/import-staging/title.ratings.tsv.gz --apply
```

Apply creates a timestamped SQLite online backup, writes IMDb rating values
and field-level provenance in one transaction, and leaves the source file
untouched. Re-running the same dataset is idempotent for provenance.


## Optional Docker-managed daily updater

The Compose stack includes an isolated `moviehub-imdb-updater` service. It shares
only the MovieHub data directory, a private subdirectory under the MovieHub data directory, a
read-only JSON configuration file, and a small state directory. It does not
expose a port and does not run inside the API process. The updater image reuses
the backend image; it adds no cron package or separate database.

The tracked default control file is `deploy/imdb-update.json`. It is mounted
read-only inside the updater and re-read every 30 seconds, so editing this file
does not require rebuilding or recreating the container. The safe defaults are
disabled and dry-run-only:

```json
{
  "enabled": false,
  "run_at": "04:30",
  "timezone": "Asia/Singapore",
  "auto_apply": false,
  "min_matched": 10,
  "backup_keep": 7,
  "retry_minutes": 15
}
```

After verifying that the production database is on schema v5 and that the
mapped paths are correct, enable scheduling by setting `enabled` to `true`.
Keep `auto_apply` false for an initial observation period. Set it to true only
after reviewing successful dry-run results. The service checks once per day
after the configured local time, retries failures at the configured interval,
uses ETag or Last-Modified to avoid unnecessary downloads, and falls back to a
download SHA-256 when the server provides neither validator. Downloads are
written to a temporary file, fully read through gzip validation, and atomically
renamed before import.

The updater state and latest result are written under the existing writable
MovieHub data volume at `/data/imdb-update-state/state.json` (host-side
`data/imdb-update-state/state.json`). Logs are available with
`docker compose logs -f moviehub-imdb-updater`. The updater holds a process
lock to prevent overlapping instances. Backup retention applies only to the
IMDb importer backup filename pattern; it does not remove migration or general
MovieHub backups.

Example deployment after the v5 migration has been reviewed and completed:

```sh
cd /volume1/docker/moviehub
docker compose config
docker compose up -d --build moviehub-imdb-updater
docker compose logs -f moviehub-imdb-updater
```

Do not enable automatic application before the production schema and local
database permissions have been verified. No NPM restart is required.
