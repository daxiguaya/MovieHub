"""Safety regression tests for the MovieHub SQLite migration runner."""

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate import execute_migration, get_schema_version

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
