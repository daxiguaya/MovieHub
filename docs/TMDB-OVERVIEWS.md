# TMDB synopsis enrichment

MovieHub is a privately hosted, non-commercial personal project. TMDB's developer API is free for non-commercial use when TMDB is attributed as the source. The application must retain the TMDB logo and the required notice in its About/Credits area:

> This product uses the TMDB API but is not endorsed or certified by TMDB.

MovieHub already provides this notice and a TMDB logo on `/credits`. Keep that page visible in the application navigation/footer. See the [TMDB FAQ](https://developer.themoviedb.org/docs/faq) and [official API documentation](https://developer.themoviedb.org/docs/getting-started).

## Safe import

The importer only accepts TMDB matches already verified by exact title/year or the existing stricter IMDb/director identity checks. It fills empty `movies.overview` fields, does not replace non-empty non-TMDB descriptions, and records a `movie_metadata_provenance` row containing the provider, source URL, observation time and SHA-256 digest. Synopsis text and API tokens are never printed in reports.

Before writing, it creates an online SQLite backup using SQLite's backup API and verifies the backup with `PRAGMA integrity_check`. The import itself is one database transaction. A dry run performs provider lookups but does not create a backup or write the database.

TMDB's API Terms limit caching TMDB information to no longer than six months. The importer uses a 170-day refresh threshold for synopsis values whose current text hash matches a TMDB provenance record. If a refresh succeeds, it updates the text and observation time. If the provider no longer supplies the synopsis or the refresh fails, it clears that expired TMDB synopsis rather than retaining it beyond the cache window. Non-TMDB overview values are not touched.

## Synology commands

From `/volume1/docker/moviehub`:

```sh
# Fetch and report only; no database write.
sh deploy/enrich_tmdb_overviews.sh --dry-run

# Explicitly apply after reviewing the dry-run summary.
sh deploy/enrich_tmdb_overviews.sh --apply
```

The wrapper builds only the backend image and runs the importer in a disposable one-off container. It does not recreate or restart the running backend, frontend, NPM, or any other service.

Run the refresh before 170 days have elapsed since the previous TMDB synopsis observation. A periodic reminder or scheduled task is recommended so expired provider content is refreshed or purged on time.
