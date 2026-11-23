"""Safety regression tests for the MovieHub SQLite migration runner."""

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate import execute_migration

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "001_moviehub_core.sql"
)


def _create_empty_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()


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


def test_initial_migration_creates_schema_and_is_idempotent(tmp_path):
    db_path = tmp_path / "movies.db"
    _create_empty_database(db_path)

    assert execute_migration(db_path, MIGRATION) == 1
    assert execute_migration(db_path, MIGRATION) == 1

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 1
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
        } <= tables
    finally:
        conn.close()

    backups = list(tmp_path.glob("*.pre-migration-*.bak"))
    assert len(backups) == 1


def test_initial_migration_refuses_nonempty_database(tmp_path):
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
    _create_empty_database(db_path)
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
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    backups = list(tmp_path.glob("*.pre-migration-*.bak"))
    assert len(backups) == 1
    assert backups[0].is_file()


def test_failed_restore_removes_stale_wal_sidecars(tmp_path, monkeypatch):
    import scripts.migrate as migrate_module

    db_path = tmp_path / "wal-movies.db"
    _create_empty_database(db_path)
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
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_validation_rejects_schema_drift_in_an_existing_database(tmp_path):
    from scripts.migrate import validate_migration

    db_path = tmp_path / "movies.db"
    _create_empty_database(db_path)
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
    _create_empty_database(db_path)
    execute_migration(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE movie_posters")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="table mismatch|no such table"):
        validate_orm_schema_contract(db_path)


def test_concurrent_initial_migrations_are_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "concurrent.db"
    _create_empty_database(db_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(execute_migration, db_path, MIGRATION)
            for _ in range(2)
        ]
        results = [future.result(timeout=30) for future in futures]

    assert results == [1, 1]

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=1"
        ).fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    assert len(list(tmp_path.glob("*.pre-migration-*.bak"))) == 1
    assert Path(str(db_path) + ".migration.lock").exists()
