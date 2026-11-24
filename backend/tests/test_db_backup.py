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


def test_backup_retention_keeps_only_the_requested_number_of_generations(tmp_path):
    database = tmp_path / "data" / "movies.db"
    backup_root = tmp_path / "backups"
    _initialize_database(database)

    first = create_backup(database, backup_root, keep_last=1)
    second = create_backup(database, backup_root, keep_last=1)

    remaining = [
        path
        for path in backup_root.iterdir()
        if path.is_dir() and path.name.startswith("moviehub-")
    ]
    assert first != second
    assert remaining == [second]


def test_backup_rejects_database_with_incomplete_schema(tmp_path):
    incomplete = tmp_path / "incomplete.db"
    connection = sqlite3.connect(incomplete)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)"
        )
        connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="missing required tables"):
        create_backup(incomplete, tmp_path / "backups")



def test_backup_retention_does_not_delete_unrecognized_directories(tmp_path):
    database = tmp_path / "data" / "movies.db"
    backup_root = tmp_path / "backups"
    _initialize_database(database)

    owned = create_backup(database, backup_root, keep_last=1)

    foreign = backup_root / "moviehub-third-party-export"
    foreign.mkdir()
    (foreign / "movies.db").write_bytes(b"not a MovieHub backup")
    (foreign / "manifest.json").write_text(
        '{"format_version": 99, "database_file": "movies.db", '
        '"schema_version": 2}',
        encoding="utf-8",
    )

    malformed = backup_root / "moviehub-incomplete"
    malformed.mkdir()
    (malformed / "movies.db").write_bytes(b"partial")
    (malformed / "manifest.json").write_text("{not-json", encoding="utf-8")

    newer = create_backup(database, backup_root, keep_last=1)

    assert owned != newer
    assert newer.is_dir()
    assert foreign.is_dir()
    assert malformed.is_dir()



@pytest.mark.parametrize("manifest_payload", ["[]", "null", '"foreign-export"', "true", "17"])
def test_backup_retention_ignores_valid_json_non_object_manifests(
    tmp_path, manifest_payload
):
    database = tmp_path / "data" / "movies.db"
    backup_root = tmp_path / "backups"
    _initialize_database(database)

    owned = create_backup(database, backup_root, keep_last=1)
    foreign = backup_root / "moviehub-foreign-json"
    foreign.mkdir()
    (foreign / "movies.db").write_bytes(b"foreign data")
    (foreign / "manifest.json").write_text(
        manifest_payload, encoding="utf-8"
    )

    # A valid backup must still be created even when a neighboring directory
    # contains syntactically valid JSON that is not a manifest object.
    newer = create_backup(database, backup_root, keep_last=1)

    assert owned != newer
    assert newer.is_dir()
    assert foreign.is_dir()
