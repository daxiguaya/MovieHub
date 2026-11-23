"""Safety tests for verified MovieHub SQLite backup and restore."""

import sqlite3
from pathlib import Path

import pytest

from scripts.db_backup import create_backup, restore_backup
from scripts.init_db import initialize


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND_DIR / "migrations" / "001_moviehub_core.sql"


def _initialize_database(path: Path) -> None:
    initialize(path, MIGRATION)


def _insert_movie(path: Path, title: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO movies (title, type, directors, actors, rating_count)
            VALUES (?, 'movie', '[]', '[]', 0)
            """,
            (title,),
        )
        connection.commit()
    finally:
        connection.close()


def _movie_titles(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT title FROM movies ORDER BY title"
            )
        ]
    finally:
        connection.close()


def test_backup_and_restore_create_verified_backup_and_rollback_copy(tmp_path):
    database = tmp_path / "data" / "movies.db"
    backups = tmp_path / "backups"
    _initialize_database(database)
    _insert_movie(database, "Before backup")

    backup_dir = create_backup(database, backups)
    assert (backup_dir / "manifest.json").is_file()
    assert (backup_dir / "movies.db").is_file()
    assert _movie_titles(backup_dir / "movies.db") == ["Before backup"]

    _insert_movie(database, "After backup")
    rollback = restore_backup(
        backup_dir,
        database,
        confirm=True,
        service_stopped=True,
    )

    assert rollback.is_file()
    assert _movie_titles(database) == ["Before backup"]
    assert _movie_titles(rollback) == ["After backup", "Before backup"]


def test_restore_requires_explicit_confirmation_and_stopped_service(tmp_path):
    database = tmp_path / "data" / "movies.db"
    _initialize_database(database)
    _insert_movie(database, "Keep this")
    backup_dir = create_backup(database, tmp_path / "backups")

    with pytest.raises(RuntimeError, match="--confirm and --service-stopped"):
        restore_backup(backup_dir, database)

    assert _movie_titles(database) == ["Keep this"]


def test_restore_rejects_modified_backup_before_touching_current_database(tmp_path):
    database = tmp_path / "data" / "movies.db"
    _initialize_database(database)
    _insert_movie(database, "Original")
    backup_dir = create_backup(database, tmp_path / "backups")

    _insert_movie(database, "Current")
    with (backup_dir / "movies.db").open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(RuntimeError, match="SHA-256"):
        restore_backup(
            backup_dir,
            database,
            confirm=True,
            service_stopped=True,
        )

    assert _movie_titles(database) == ["Current", "Original"]
