"""Regression tests for the independent MovieHub database schema."""

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.database import Base
from scripts.init_db import initialize

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "001_moviehub_core.sql"
)
EXPECTED_TABLES = set(Base.metadata.tables) | {"schema_migrations"}


def _migrated_database(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    finally:
        conn.close()


def test_initial_migration_builds_independent_schema(tmp_path):
    db_path = tmp_path / "moviehub.db"
    _migrated_database(db_path)

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == EXPECTED_TABLES

        for table_name, table in Base.metadata.tables.items():
            expected_columns = set(table.columns.keys())
            actual_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            assert actual_columns == expected_columns, table_name

        with engine.connect() as conn:
            assert conn.exec_driver_sql(
                "SELECT MAX(version) FROM schema_migrations"
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_snapshot_uses_internal_movie_id_and_restricts_movie_delete(tmp_path):
    db_path = tmp_path / "moviehub.db"
    _migrated_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            "INSERT INTO movies(id, douban_id, title) VALUES (1, '12345', 'Test movie')"
        )
        conn.execute(
            """
            INSERT INTO lists(
                list_id, slug, name, source, category, created_at, updated_at
            ) VALUES (1, 'test-chart', 'Test chart', 'test', 'general',
                      '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO chart_snapshots(
                id, list_id, snapshot_date, imported_at, item_count
            ) VALUES (1, 1, '2026-01-01', '2026-01-01T00:00:00', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO list_items(snapshot_id, movie_id, rank, source_rating)
            VALUES (1, 1, 1, 8.5)
            """
        )

        row = conn.execute(
            """
            SELECT li.movie_id, cs.snapshot_date
            FROM list_items AS li
            JOIN chart_snapshots AS cs ON cs.id = li.snapshot_id
            """
        ).fetchone()
        assert row == (1, "2026-01-01")

        try:
            conn.execute("DELETE FROM movies WHERE id = 1")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Movie deletion should be restricted")

        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_snapshot_date_and_rank_are_unique(tmp_path):
    db_path = tmp_path / "moviehub.db"
    _migrated_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            "INSERT INTO movies(id, douban_id, title) VALUES (1, '12345', 'A')"
        )
        conn.execute(
            "INSERT INTO movies(id, douban_id, title) VALUES (2, '12346', 'B')"
        )
        conn.execute(
            """
            INSERT INTO lists(
                list_id, slug, name, source, category, created_at, updated_at
            ) VALUES (1, 'test-chart', 'Test chart', 'test', 'general',
                      '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO chart_snapshots(id, list_id, snapshot_date, imported_at, item_count)
            VALUES (1, 1, '2026-01-01', '2026-01-01T00:00:00', 1)
            """
        )
        try:
            conn.execute(
                """
                INSERT INTO chart_snapshots(list_id, snapshot_date, imported_at, item_count)
                VALUES (1, '2026-01-01', '2026-01-01T00:00:00', 0)
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("A chart/date snapshot must be unique")

        conn.execute(
            "INSERT INTO list_items(snapshot_id, movie_id, rank) VALUES (1, 1, 1)"
        )
        try:
            conn.execute(
                "INSERT INTO list_items(snapshot_id, movie_id, rank) VALUES (1, 2, 1)"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Ranks must be unique within a snapshot")
    finally:
        conn.close()



def test_explicit_initializer_creates_database_and_seeds_charts(tmp_path):
    db_path = tmp_path / "initialized" / "movies.db"
    initialize(db_path, MIGRATION)

    assert db_path.is_file()
    conn = sqlite3.connect(str(db_path))
    try:
        chart_count = conn.execute(
            "SELECT COUNT(*) FROM lists"
        ).fetchone()[0]
        assert chart_count > 0

        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()
