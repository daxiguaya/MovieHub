"""Create and restore verified backups of the MovieHub-owned SQLite database.

Examples:
    python -m scripts.db_backup backup
    python -m scripts.db_backup restore --backup-dir /backups/moviehub-... \
        --confirm --service-stopped
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_DATABASE_TABLES,
    get_db_path,
)

logger = logging.getLogger("moviehub.db_backup")
DATABASE_FILENAME = "movies.db"
BACKUP_PREFIX = "moviehub-"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_database(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Database file is missing or empty: {path}")

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:10]}"
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = REQUIRED_DATABASE_TABLES - tables
        if missing_tables:
            raise RuntimeError(
                f"Database is missing required tables: {sorted(missing_tables)}"
            )

        row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        version = row[0] if row else None
        if version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported MovieHub schema version: {version}; "
                f"expected {CURRENT_SCHEMA_VERSION}"
            )
    finally:
        connection.close()


def _sqlite_online_copy(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(
        source_path.as_uri() + "?mode=ro",
        uri=True,
        timeout=30,
    )
    destination = sqlite3.connect(destination_path, timeout=30)
    try:
        source.backup(destination)
        destination.commit()
        # Publish a self-contained SQLite file without WAL sidecars.
        journal_mode = destination.execute(
            "PRAGMA journal_mode=DELETE"
        ).fetchone()
        if not journal_mode or journal_mode[0].lower() != "delete":
            raise RuntimeError("Could not finalize standalone backup database")
    finally:
        destination.close()
        source.close()


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _prune_backups(root: Path, keep_last: int, current: Path) -> None:
    if keep_last < 1:
        raise ValueError("keep_last must be at least 1")

    candidates = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and path.name.startswith(BACKUP_PREFIX)
            and (path / "manifest.json").is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    retained = 0
    for path in candidates:
        if path == current:
            retained += 1
            continue
        if retained < keep_last:
            retained += 1
            continue
        shutil.rmtree(path)


def create_backup(
    database_path: Path | str | None = None,
    destination_root: Path | str = "/backups",
    keep_last: int = 7,
) -> Path:
    source_path = Path(database_path or get_db_path()).expanduser().resolve()
    root = Path(destination_root).expanduser().resolve()

    if keep_last < 1:
        raise ValueError("keep_last must be at least 1")
    _validate_database(source_path)
    root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_directory = root / f"{BACKUP_PREFIX}{timestamp}"
    staging_directory = Path(
        tempfile.mkdtemp(prefix=".moviehub-backup-", dir=root)
    )

    try:
        backup_file = staging_directory / DATABASE_FILENAME
        _sqlite_online_copy(source_path, backup_file)
        _validate_database(backup_file)

        manifest = {
            "format_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "database_file": DATABASE_FILENAME,
            "database_sha256": _sha256(backup_file),
            "database_size_bytes": backup_file.stat().st_size,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "source_database": str(source_path),
            "poster_cache_included": False,
        }
        _write_json_atomic(staging_directory / "manifest.json", manifest)
        os.replace(staging_directory, final_directory)
        _prune_backups(root, keep_last, final_directory)
        logger.info("Verified MovieHub backup created: %s", final_directory)
        return final_directory
    except Exception:
        if staging_directory.exists():
            shutil.rmtree(staging_directory, ignore_errors=True)
        raise


def restore_backup(
    backup_directory: Path | str,
    database_path: Path | str | None = None,
    *,
    confirm: bool = False,
    service_stopped: bool = False,
) -> Path | None:
    if not confirm or not service_stopped:
        raise RuntimeError(
            "Restore requires both --confirm and --service-stopped. "
            "Stop the MovieHub API container before restoring."
        )

    backup_root = Path(backup_directory).expanduser().resolve()
    target_path = Path(database_path or get_db_path()).expanduser().resolve()
    manifest_path = backup_root / "manifest.json"
    backup_file = backup_root / DATABASE_FILENAME

    if not manifest_path.is_file() or not backup_file.is_file():
        raise FileNotFoundError("Backup must contain manifest.json and movies.db")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise RuntimeError("Unsupported backup manifest format")
    if manifest.get("database_file") != DATABASE_FILENAME:
        raise RuntimeError("Unexpected database filename in backup manifest")
    if manifest.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise RuntimeError("Backup schema version is not supported")
    if _sha256(backup_file) != manifest.get("database_sha256"):
        raise RuntimeError("Backup SHA-256 verification failed")

    _validate_database(backup_file)
    if backup_file == target_path:
        raise RuntimeError("Backup source and restore destination must differ")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rollback_path = target_path.with_name(
        f"{target_path.name}.pre-restore-{timestamp}"
    )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".restore.tmp",
        dir=target_path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)

    had_existing_database = target_path.exists()

    try:
        shutil.copyfile(backup_file, temporary_path)
        _validate_database(temporary_path)

        if target_path.exists():
            # The operator must have stopped the API before this command.
            connection = sqlite3.connect(target_path, timeout=30)
            try:
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint and checkpoint[0] != 0:
                    raise RuntimeError(
                        "Could not checkpoint the live database before restore: "
                        f"{checkpoint}"
                    )
                journal_mode = connection.execute(
                    "PRAGMA journal_mode=DELETE"
                ).fetchone()
                if not journal_mode or journal_mode[0].lower() != "delete":
                    raise RuntimeError(
                        "Could not switch the stopped database to DELETE journal mode"
                    )
            finally:
                connection.close()

            _sqlite_online_copy(target_path, rollback_path)
            _validate_database(rollback_path)

        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(target_path) + suffix).unlink(missing_ok=True)

        os.replace(temporary_path, target_path)
        try:
            _validate_database(target_path)
        except Exception:
            if rollback_path.exists():
                os.replace(rollback_path, target_path)
            else:
                target_path.unlink(missing_ok=True)
            raise

        logger.warning(
            "MovieHub database restored from %s. Pre-restore copy: %s",
            backup_root,
            rollback_path if rollback_path.exists() else "not applicable",
        )
        return rollback_path if had_existing_database else None
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or restore a verified MovieHub SQLite backup"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument(
        "--destination",
        type=Path,
        default=Path(os.getenv("MOVIEHUB_BACKUP_DIR", "/backups")),
    )
    backup_parser.add_argument("--keep-last", type=int, default=7)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup-dir", type=Path, required=True)
    restore_parser.add_argument("--confirm", action="store_true")
    restore_parser.add_argument("--service-stopped", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        if args.command == "backup":
            result = create_backup(
                destination_root=args.destination,
                keep_last=args.keep_last,
            )
            print(result)
        else:
            result = restore_backup(
                args.backup_dir,
                confirm=args.confirm,
                service_stopped=args.service_stopped,
            )
            if result:
                print(f"Pre-restore rollback copy: {result}")
            else:
                print("Restored database; no previous database existed.")
        return 0
    except Exception:
        logger.exception("MovieHub database backup operation failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
