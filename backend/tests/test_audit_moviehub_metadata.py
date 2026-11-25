import sqlite3

from scripts.audit_moviehub_metadata import audit_database


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE movies (
            id INTEGER PRIMARY KEY,
            douban_id TEXT,
            imdb_id TEXT,
            tmdb_id TEXT,
            title TEXT NOT NULL,
            original_title TEXT,
            year INTEGER,
            rating REAL,
            rating_count INTEGER,
            directors TEXT NOT NULL DEFAULT '[]',
            actors TEXT NOT NULL DEFAULT '[]',
            overview TEXT,
            douban_url TEXT
        );
        CREATE TABLE movie_metadata_provenance (
            id INTEGER PRIMARY KEY,
            movie_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            source TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL
        );
        CREATE TABLE lists (
            list_id INTEGER PRIMARY KEY,
            slug TEXT,
            name TEXT,
            source TEXT
        );
        CREATE TABLE chart_snapshots (
            id INTEGER PRIMARY KEY,
            list_id INTEGER,
            item_count INTEGER
        );
        CREATE TABLE list_items (
            snapshot_id INTEGER,
            movie_id INTEGER
        );
        CREATE TABLE movie_genres (movie_id INTEGER, genre_id INTEGER);
        CREATE TABLE movie_regions (movie_id INTEGER, region_id INTEGER);
        CREATE TABLE movie_posters (movie_id INTEGER, url TEXT);
        CREATE TABLE schema_migrations (version INTEGER);
        INSERT INTO schema_migrations VALUES (4);
        INSERT INTO movies (
            id, douban_id, title, tmdb_id, year, rating, rating_count,
            directors, actors, overview
        ) VALUES
            (1, '123', 'Film One', '278', 1994, 9.7, 100, '["Director"]', '["Actor"]', NULL),
            (2, '456', 'Film Two', NULL, 2020, 8.1, NULL, '[]', '[]', 'Synopsis');
        INSERT INTO movie_metadata_provenance
            (movie_id, field_name, source, source_url, observed_at)
        VALUES (2, 'overview', 'tmdb', '', '2026-01-01');
        INSERT INTO lists VALUES (1, 'top250', 'Top 250', 'douban');
        INSERT INTO chart_snapshots VALUES (1, 1, 2);
        INSERT INTO list_items VALUES (1, 1);
        INSERT INTO list_items VALUES (1, 2);
        INSERT INTO movie_genres VALUES (1, 1);
        INSERT INTO movie_posters VALUES (1, 'https://example.invalid/poster');
        """
    )
    connection.commit()
    connection.close()


def test_audit_reports_existing_moviehub_coverage_and_provenance(tmp_path):
    path = tmp_path / "movies.db"
    _database(path)

    report = audit_database(path)

    assert report["read_only"] is True
    assert report["movie_count"] == 2
    assert report["schema_version"] == 4
    assert report["identity_coverage"]["douban_id"]["present"] == 2
    assert report["identity_coverage"]["tmdb_id"]["present"] == 1
    assert report["metadata_coverage"]["overview"]["present"] == 1
    assert report["provenance"]["movies_with_observation_by_field"]["overview"]["movies_with_observation"] == 1
    assert report["charts"][0]["distinct_movies"] == 2
    assert report["diagnostics"]["overview_populated_without_provenance"] == 0

    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0] == 2
    connection.close()


def test_audit_rejects_non_moviehub_database(tmp_path):
    path = tmp_path / "not-moviehub.db"
    sqlite3.connect(path).close()

    try:
        audit_database(path)
    except ValueError as exc:
        assert "Not a complete MovieHub database" in str(exc)
    else:
        raise AssertionError("expected incomplete database to be rejected")
