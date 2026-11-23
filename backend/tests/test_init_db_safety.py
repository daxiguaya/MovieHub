"""Safety tests for explicit MovieHub database initialization."""

import sqlite3
from pathlib import Path

import pytest

from scripts.init_db import initialize

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "001_moviehub_core.sql"
)


def test_initializer_refuses_existing_nonempty_database_without_changes(tmp_path):
    db_path = tmp_path / "existing.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE scout_data (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO scout_data(id, title) VALUES (1, 'preserve me')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="non-empty"):
        initialize(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT id, title FROM scout_data"
        ).fetchall() == [(1, "preserve me")]
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("scout_data",)]
    finally:
        conn.close()


def test_initializer_can_initialize_precreated_empty_file(tmp_path):
    db_path = tmp_path / "empty" / "movies.db"
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    initialize(db_path, MIGRATION)

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
