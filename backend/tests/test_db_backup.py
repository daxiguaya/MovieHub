"""Safety tests for verified MovieHub SQLite backup and restore."""

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import db_backup as db_backup_module
from scripts.db_backup import create_backup, restore_backup
from app.database import database_is_ready
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

    with pytest.raises(RuntimeError, match="database size|SHA-256"):
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



def test_backup_retention_never_follows_symlinked_backup_directories(tmp_path):
    database = tmp_path / "data" / "movies.db"
    backup_root = tmp_path / "backups"
    external = tmp_path / "external-export"
    _initialize_database(database)

    external.mkdir()
    (external / "movies.db").write_bytes(b"external data")
    (external / "manifest.json").write_text(
        '{"format_version": 1, "database_file": "movies.db", '
        '"schema_version": 2}',
        encoding="utf-8",
    )
    backup_root.mkdir()
    link = backup_root / "moviehub-external-link"
    link.symlink_to(external, target_is_directory=True)

    created = create_backup(database, backup_root, keep_last=1)

    assert created.is_dir()
    assert link.is_symlink()
    assert external.is_dir()
    assert (external / "movies.db").read_bytes() == b"external data"



@pytest.mark.parametrize(
    ("manifest_kind", "expected_error"),
    [
        ("array", "JSON object"),
        ("null", "JSON object"),
        ("boolean-format-version", "manifest format"),
        ("boolean-schema-version", "schema version"),
        ("wrong-size", "database size"),
        ("invalid-digest", "SHA-256 digest"),
        ("malformed-json", "read backup manifest"),
    ],
)
def test_restore_rejects_invalid_manifest_without_touching_current_database(
    tmp_path, manifest_kind, expected_error
):
    database = tmp_path / "data" / "movies.db"
    _initialize_database(database)
    _insert_movie(database, "Current database must survive")
    backup_dir = create_backup(database, tmp_path / "backups")
    manifest_path = backup_dir / "manifest.json"

    if manifest_kind == "array":
        manifest_path.write_text("[]", encoding="utf-8")
    elif manifest_kind == "null":
        manifest_path.write_text("null", encoding="utf-8")
    elif manifest_kind == "malformed-json":
        manifest_path.write_text("{broken", encoding="utf-8")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_kind == "boolean-format-version":
            manifest["format_version"] = True
        elif manifest_kind == "boolean-schema-version":
            manifest["schema_version"] = True
        elif manifest_kind == "wrong-size":
            manifest["database_size_bytes"] += 1
        elif manifest_kind == "invalid-digest":
            manifest["database_sha256"] = "not-a-sha256"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match=expected_error):
        restore_backup(
            backup_dir,
            database,
            confirm=True,
            service_stopped=True,
        )

    assert _movie_titles(database) == ["Current database must survive"]



@pytest.mark.parametrize("symlink_kind", ["directory", "manifest", "database"])
def test_restore_rejects_symlinked_backup_inputs_without_touching_target(
    tmp_path, symlink_kind
):
    database = tmp_path / "data" / "movies.db"
    _initialize_database(database)
    _insert_movie(database, "Target must survive")
    backup_dir = create_backup(database, tmp_path / "backups")
    supplied = tmp_path / "supplied-backup"

    if symlink_kind == "directory":
        supplied.symlink_to(backup_dir, target_is_directory=True)
    else:
        supplied.mkdir()
        for name in ("manifest.json", "movies.db"):
            source = backup_dir / name
            destination = supplied / name
            if name == ("manifest.json" if symlink_kind == "manifest" else "movies.db"):
                destination.symlink_to(source)
            else:
                destination.write_bytes(source.read_bytes())

    with pytest.raises(RuntimeError, match="symbolic link"):
        restore_backup(
            supplied,
            database,
            confirm=True,
            service_stopped=True,
        )

    assert _movie_titles(database) == ["Target must survive"]


def test_restore_rolls_back_original_database_if_post_replace_validation_fails(
    tmp_path, monkeypatch
):
    database = tmp_path / "data" / "movies.db"
    _initialize_database(database)
    _insert_movie(database, "Original state")
    backup_dir = create_backup(database, tmp_path / "backups")

    _insert_movie(database, "Current state")
    original_validate = db_backup_module._validate_database

    def fail_restored_target(path):
        if Path(path) == database:
            raise RuntimeError("injected post-replace validation failure")
        return original_validate(path)

    monkeypatch.setattr(db_backup_module, "_validate_database", fail_restored_target)

    with pytest.raises(RuntimeError, match="post-replace validation failure"):
        restore_backup(
            backup_dir,
            database,
            confirm=True,
            service_stopped=True,
        )

    assert _movie_titles(database) == ["Current state", "Original state"]


def test_full_deployment_lifecycle_initialize_backup_restore_and_readiness(tmp_path):
    database = tmp_path / "isolated-data" / "db" / "movies.db"
    backup_root = tmp_path / "isolated-backups"

    assert database_is_ready(database) is False
    _initialize_database(database)
    assert database_is_ready(database) is True

    _insert_movie(database, "Known good pre-backup state")
    backup_dir = create_backup(database, backup_root)
    assert (backup_dir / "manifest.json").is_file()

    _insert_movie(database, "Post-backup change")
    assert _movie_titles(database) == [
        "Known good pre-backup state",
        "Post-backup change",
    ]

    rollback = restore_backup(
        backup_dir,
        database,
        confirm=True,
        service_stopped=True,
    )

    assert rollback is not None and rollback.is_file()
    assert _movie_titles(database) == ["Known good pre-backup state"]
    assert _movie_titles(rollback) == [
        "Known good pre-backup state",
        "Post-backup change",
    ]
    assert database_is_ready(database) is True

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 5
    finally:
        connection.close()


def test_initializer_refuses_existing_external_database_without_mutation(tmp_path):
    external_database = tmp_path / "external-source" / "scout.db"
    external_database.parent.mkdir(parents=True)
    connection = sqlite3.connect(external_database)
    try:
        connection.execute(
            "CREATE TABLE scout_records (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO scout_records (title) VALUES ('Scout data must remain untouched')"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="Refusing to initialize a non-empty database"):
        _initialize_database(external_database)

    connection = sqlite3.connect(external_database)
    try:
        assert connection.execute(
            "SELECT title FROM scout_records"
        ).fetchall() == [("Scout data must remain untouched",)]
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='movies'"
        ).fetchone()[0] == 0
    finally:
        connection.close()
