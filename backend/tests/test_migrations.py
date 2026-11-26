"""Safety regression tests for the MovieHub SQLite migration runner."""

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate import execute_migration

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "005_imdb_ratings.sql"
)


def _create_empty_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()

def _create_v2_database(path: Path) -> None:
    """Create an isolated, valid schema-v2 fixture for the v2 -> v3 runner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    initial = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "001_moviehub_core.sql"
    )
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(initial.read_text(encoding="utf-8"))
        followup = initial.parent / "002_durable_import_batch_receipts.sql"
        conn.executescript(followup.read_text(encoding="utf-8"))
    finally:
        conn.close()


def test_check_only_does_not_modify_empty_database(tmp_path):
    db_path = tmp_path / "movies.db"
    _create_empty_database(db_path)

    result = execute_migration(db_path, MIGRATION, check_only=True)

    assert result == 0
    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []
    finally:
        conn.close()
    assert not list(tmp_path.glob("*.pre-migration-*.bak"))


def test_version_five_migration_upgrades_v2_and_is_idempotent(tmp_path):
    db_path = tmp_path / "movies.db"
    _create_v2_database(db_path)

    assert execute_migration(db_path, MIGRATION) == 5
    assert execute_migration(db_path, MIGRATION) == 4

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 4
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "movies", "genres", "regions", "movie_genres",
            "movie_regions", "movie_posters", "lists",
            "chart_snapshots", "list_items", "favorites",
            "schema_migrations",
            "import_batch_receipts",
            "movie_metadata_provenance",
        } <= tables
    finally:
        conn.close()

    backups = list(tmp_path.glob("*.pre-migration-*.bak"))
    assert len(backups) == 1


def test_migration_refuses_unversioned_nonempty_database(tmp_path):
    db_path = tmp_path / "scout-or-other.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE existing_data (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="non-empty"):
        execute_migration(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("existing_data",)]
    finally:
        conn.close()
    assert not list(tmp_path.glob("*.pre-migration-*.bak"))


def test_migration_refuses_database_with_newer_schema_version(tmp_path):
    db_path = tmp_path / "newer.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES (99, 'future', '2099-01-01')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="newer"):
        execute_migration(db_path, MIGRATION)


def test_failed_migration_restores_pre_migration_backup(tmp_path):
    db_path = tmp_path / "movies.db"
    _create_v2_database(db_path)
    broken_migration = tmp_path / "broken.sql"
    broken_migration.write_text(
        "BEGIN IMMEDIATE; CREATE TABLE partial_change (id INTEGER); "
        "THIS IS NOT VALID SQL; COMMIT;",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.OperationalError):
        execute_migration(db_path, broken_migration)

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    backups = list(tmp_path.glob("*.pre-migration-*.bak"))
    assert len(backups) == 1
    assert backups[0].is_file()


def test_failed_restore_removes_stale_wal_sidecars(tmp_path, monkeypatch):
    import scripts.migrate as migrate_module

    db_path = tmp_path / "wal-movies.db"
    _create_v2_database(db_path)
    migration = tmp_path / "valid-but-incomplete.sql"
    migration.write_text(
        "BEGIN IMMEDIATE; "
        "CREATE TABLE partial_change (id INTEGER PRIMARY KEY); "
        "COMMIT;",
        encoding="utf-8",
    )

    def fail_validation(path, expected_version=migrate_module.MIGRATION_VERSION):
        Path(str(path) + "-wal").write_bytes(b"stale wal")
        Path(str(path) + "-shm").write_bytes(b"stale shm")
        raise RuntimeError("simulated post-migration validation failure")

    monkeypatch.setattr(migrate_module, "validate_migration", fail_validation)

    with pytest.raises(RuntimeError, match="simulated post-migration"):
        migrate_module.execute_migration(db_path, migration)

    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()
    assert not Path(str(db_path) + "-journal").exists()

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_validation_rejects_schema_drift_in_an_existing_database(tmp_path):
    from scripts.migrate import validate_migration

    db_path = tmp_path / "movies.db"
    _create_v2_database(db_path)
    execute_migration(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP INDEX ix_movies_rating_id")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="Index mismatch in movies"):
        validate_migration(db_path)


def test_validation_rejects_missing_foreign_key_contract(tmp_path):
    from scripts.migrate import validate_orm_schema_contract

    db_path = tmp_path / "movies.db"
    _create_v2_database(db_path)
    execute_migration(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE movie_posters")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="table mismatch|no such table"):
        validate_orm_schema_contract(db_path)


def test_concurrent_v2_migrations_are_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "concurrent.db"
    _create_v2_database(db_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(execute_migration, db_path, MIGRATION)
            for _ in range(2)
        ]
        results = [future.result(timeout=30) for future in futures]

    assert results == [4, 4]

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=4"
        ).fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    assert len(list(tmp_path.glob("*.pre-migration-*.bak"))) == 1
    assert Path(str(db_path) + ".migration.lock").exists()



def test_v4_migration_preserves_existing_catalogue_and_user_data(tmp_path):
    """A populated v2 database must retain every user-facing relation on v3."""
    db_path = tmp_path / "populated-v1.db"
    _create_v2_database(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            INSERT INTO movies (
                id, douban_id, title, original_title, year, rating,
                rating_count, type, directors, actors, overview,
                douban_url, updated_at
            ) VALUES (
                41, '1292052', '肖申克的救赎', 'The Shawshank Redemption',
                1994, 9.7, 2500000, 'movie', '["弗兰克·德拉邦特"]',
                '["蒂姆·罗宾斯"]', 'fixture overview',
                'https://movie.douban.com/subject/1292052/', 1800000000
            )
            """
        )
        conn.execute("INSERT INTO movies (id, douban_id, title, rating_count) VALUES (42, 'zero-votes', '年度榜缺失人数', 0)")
        conn.execute("INSERT INTO genres(id, name) VALUES (7, '剧情')")
        conn.execute("INSERT INTO regions(id, name) VALUES (8, '美国')")
        conn.execute(
            "INSERT INTO movie_genres(movie_id, genre_id) VALUES (41, 7)"
        )
        conn.execute(
            "INSERT INTO movie_regions(movie_id, region_id) VALUES (41, 8)"
        )
        conn.execute(
            "INSERT INTO movie_posters(movie_id, url) VALUES (41, 'https://img.example/poster.jpg')"
        )
        conn.execute(
            """
            INSERT INTO lists (
                list_id, slug, name, source, category, period, description,
                enabled, display_order, created_at, updated_at
            ) VALUES (
                9, 'fixture-chart', 'Fixture chart', 'douban', 'top',
                NULL, 'migration preservation fixture', 1, 10,
                '2026-01-01 00:00:00', '2026-01-01 00:00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chart_snapshots (
                id, list_id, snapshot_date, imported_at, item_count
            ) VALUES (11, 9, '2026-01-01', '2026-01-01 00:00:00', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO list_items(snapshot_id, movie_id, rank, source_rating)
            VALUES (11, 41, 1, 9.7)
            """
        )
        conn.execute(
            """
            INSERT INTO favorites(movie_id, created_at, note)
            VALUES (41, '2026-01-02 00:00:00', 'keep this note')
            """
        )
        conn.commit()
    finally:
        conn.close()

    assert execute_migration(db_path, MIGRATION) == 4

    backup_path = next(tmp_path.glob("populated-v1.db.pre-migration-*.bak"))
    for candidate in (db_path, backup_path):
        check = sqlite3.connect(str(candidate))
        try:
            assert check.execute(
                "SELECT title, original_title, overview FROM movies WHERE id=41"
            ).fetchone() == (
                "肖申克的救赎",
                "The Shawshank Redemption",
                "fixture overview",
            )
            assert check.execute(
                "SELECT name FROM genres WHERE id=7"
            ).fetchone() == ("剧情",)
            assert check.execute(
                "SELECT name FROM regions WHERE id=8"
            ).fetchone() == ("美国",)
            assert check.execute(
                "SELECT movie_id, genre_id FROM movie_genres"
            ).fetchall() == [(41, 7)]
            assert check.execute(
                "SELECT movie_id, region_id FROM movie_regions"
            ).fetchall() == [(41, 8)]
            assert check.execute(
                "SELECT movie_id, url FROM movie_posters"
            ).fetchall() == [(41, "https://img.example/poster.jpg")]
            assert check.execute(
                "SELECT slug, name FROM lists WHERE list_id=9"
            ).fetchone() == ("fixture-chart", "Fixture chart")
            assert check.execute(
                "SELECT list_id, snapshot_date, item_count FROM chart_snapshots WHERE id=11"
            ).fetchone() == (9, "2026-01-01", 1)
            assert check.execute(
                "SELECT snapshot_id, movie_id, rank, source_rating FROM list_items"
            ).fetchall() == [(11, 41, 1, 9.7)]
            assert check.execute(
                "SELECT movie_id, note FROM favorites"
            ).fetchall() == [(41, "keep this note")]
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            check.close()

    migrated = sqlite3.connect(str(db_path))
    try:
        assert migrated.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 4
        assert migrated.execute(
            "SELECT COUNT(*) FROM import_batch_receipts"
        ).fetchone()[0] == 0
        assert migrated.execute(
            "SELECT rating_count FROM movies WHERE id=42"
        ).fetchone()[0] is None
    finally:
        migrated.close()
