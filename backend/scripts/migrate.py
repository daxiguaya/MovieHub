
#!/usr/bin/env python3
"""MovieHub SQLite schema migration runner.

Features:
- Detects the current schema version.
- Creates a consistent SQLite backup before migration.
- Executes numbered SQL migrations exactly once.
- Validates SQLite integrity, foreign keys and required schema objects.
- Restores the backup if migration or validation fails.

Run from the backend directory:
    python -m scripts.migrate

Optional:
    python -m scripts.migrate --db /path/to/movies.db
    python -m scripts.migrate --migration /path/to/001_moviehub_core.sql
    python -m scripts.migrate --check-only
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger("moviehub.migrate")

MIGRATION_VERSION = 1
MIGRATION_FILENAME = "001_moviehub_core.sql"

REQUIRED_MOVIE_COLUMNS = {
    "id",
    "douban_id",
    "imdb_id",
    "tmdb_id",
    "title",
    "original_title",
    "year",
    "rating",
    "rating_count",
    "type",
    "updated_at",
    "directors",
    "actors",
    "overview",
    "douban_url",
}

REQUIRED_TABLES = {
    "movies",
    "genres",
    "regions",
    "movie_genres",
    "movie_regions",
    "movie_posters",
    "lists",
    "list_items",
    "favorites",
    "schema_migrations",
}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_default_database_path() -> Path:
    """Resolve the same database path used by the FastAPI application."""
    try:
        from app.database import get_db_path

        return Path(get_db_path()).expanduser().resolve()
    except Exception as exc:
        raise RuntimeError(
            "Could not load the application database path. "
            "Run this command from the backend directory and check "
            "the application configuration."
        ) from exc


def get_default_migration_path() -> Path:
    """Resolve the migration SQL relative to this script."""
    backend_dir = Path(__file__).resolve().parents[1]
    return backend_dir / "migrations" / MIGRATION_FILENAME


def open_database(path: Path) -> sqlite3.Connection:
    """Open a database with foreign-key enforcement enabled."""
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name = ?
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return row is not None


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return zero when this database has not been migrated yet."""
    if not table_exists(conn, "schema_migrations"):
        return 0

    row = conn.execute(
        "SELECT MAX(version) AS version FROM schema_migrations"
    ).fetchone()

    if row is None or row["version"] is None:
        return 0

    return int(row["version"])


def create_backup(database_path: Path) -> Path:
    """Create a consistent backup using SQLite's online backup API."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(
        f"{database_path.name}.pre-migration-{timestamp}.bak"
    )

    if backup_path.exists():
        raise FileExistsError(
            f"Backup path already exists: {backup_path}"
        )

    source = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=60,
    )
    destination = sqlite3.connect(str(backup_path), timeout=60)

    try:
        source.backup(destination)
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        if backup_path.exists():
            backup_path.unlink()
        raise
    else:
        destination.close()
        source.close()

    # Verify the backup before it is trusted for rollback.
    validate_sqlite_integrity(backup_path)

    logger.info("Backup created: %s", backup_path)
    return backup_path


def validate_sqlite_integrity(database_path: Path) -> None:
    """Run SQLite's built-in integrity check."""
    conn = sqlite3.connect(str(database_path), timeout=60)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(
                f"SQLite integrity_check failed for {database_path}: "
                f"{result[0] if result else 'no result'}"
            )
    finally:
        conn.close()


def validate_foreign_keys(conn: sqlite3.Connection) -> None:
    """Fail if any foreign-key violations exist."""
    errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if errors:
        preview = [tuple(row) for row in errors[:10]]
        raise RuntimeError(
            f"Foreign-key validation failed; first errors: {preview}"
        )


def validate_movie_columns(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "movies"):
        raise RuntimeError("Required table 'movies' does not exist")

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(movies)")
    }

    missing = REQUIRED_MOVIE_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "MovieHub migration is incomplete; missing movies columns: "
            + ", ".join(sorted(missing))
        )


def validate_required_tables(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    missing = REQUIRED_TABLES - existing
    if missing:
        raise RuntimeError(
            "MovieHub migration is incomplete; missing tables: "
            + ", ".join(sorted(missing))
        )


def validate_douban_ids(conn: sqlite3.Connection) -> None:
    """Every movie must have one unique, non-empty Douban identifier."""
    missing_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM movies
        WHERE douban_id IS NULL OR TRIM(douban_id) = ''
        """
    ).fetchone()[0]

    if missing_count:
        raise RuntimeError(
            f"{missing_count} movie rows have an empty Douban ID"
        )

    duplicate = conn.execute(
        """
        SELECT douban_id, COUNT(*) AS count
        FROM movies
        GROUP BY douban_id
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()

    if duplicate:
        raise RuntimeError(
            "Duplicate Douban ID found: "
            f"{duplicate['douban_id']} ({duplicate['count']} rows)"
        )


def validate_migration(
    database_path: Path,
    expected_version: int = MIGRATION_VERSION,
) -> None:
    """Validate the migrated database as a whole."""
    validate_sqlite_integrity(database_path)

    conn = open_database(database_path)
    try:
        version = get_schema_version(conn)
        if version != expected_version:
            raise RuntimeError(
                f"Schema version mismatch: expected {expected_version}, "
                f"got {version}"
            )

        validate_required_tables(conn)
        validate_movie_columns(conn)
        validate_douban_ids(conn)
        validate_foreign_keys(conn)

    finally:
        conn.close()


def restore_backup(
    backup_path: Path,
    database_path: Path,
) -> None:
    """Restore a backup through a temporary file and atomic replacement."""
    restore_path = database_path.with_name(
        database_path.name + ".restore.tmp"
    )

    if restore_path.exists():
        restore_path.unlink()

    source = sqlite3.connect(
        f"file:{backup_path}?mode=ro",
        uri=True,
        timeout=60,
    )
    destination = sqlite3.connect(str(restore_path), timeout=60)

    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    validate_sqlite_integrity(restore_path)
    os.replace(restore_path, database_path)

    logger.warning("Original database restored from: %s", backup_path)


def execute_migration(
    database_path: Path,
    migration_path: Path,
    check_only: bool = False,
) -> int:
    """Execute the pending migration and return the resulting version."""
    if not database_path.is_file():
        raise FileNotFoundError(
            f"Database file does not exist: {database_path}"
        )

    if not migration_path.is_file():
        raise FileNotFoundError(
            f"Migration SQL file does not exist: {migration_path}"
        )

    migration_sql = migration_path.read_text(encoding="utf-8").strip()
    if not migration_sql:
        raise RuntimeError("Migration SQL file is empty")

    with open_database(database_path) as conn:
        current_version = get_schema_version(conn)

    logger.info("Current schema version: %s", current_version)
    logger.info("Target schema version: %s", MIGRATION_VERSION)

    if current_version > MIGRATION_VERSION:
        raise RuntimeError(
            "Database schema is newer than this migration runner. "
            "Refusing to downgrade or modify it."
        )

    if current_version == MIGRATION_VERSION:
        logger.info("Database is already at the requested version")
        validate_migration(database_path)
        logger.info("Existing MovieHub schema passed validation")
        return current_version

    if current_version != 0:
        raise RuntimeError(
            f"Unsupported starting schema version: {current_version}. "
            "A dedicated migration is required."
        )

    if check_only:
        logger.info(
            "Check-only mode: migration is pending; no changes made"
        )
        return current_version

    backup_path = create_backup(database_path)
    migration_started = False

    try:
        logger.info("Executing migration SQL: %s", migration_path)

        # executescript runs the explicit BEGIN/COMMIT statements contained
        # in the migration SQL file. The SQL file controls its transaction.
        conn = open_database(database_path)
        try:
            migration_started = True
            conn.executescript(migration_sql)
        finally:
            conn.close()

        validate_migration(database_path)

        logger.info(
            "Migration completed and validated. Schema version: %s",
            MIGRATION_VERSION,
        )
        logger.info("Pre-migration backup retained at: %s", backup_path)

        return MIGRATION_VERSION

    except Exception:
        logger.exception("Migration failed")

        if migration_started:
            try:
                restore_backup(backup_path, database_path)
            except Exception:
                logger.exception(
                    "CRITICAL: automatic database restoration failed. "
                    "Do not start the application. "
                    "The backup is retained at: %s",
                    backup_path,
                )

        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MovieHub SQLite schema migration runner"
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path; defaults to the application setting",
    )

    parser.add_argument(
        "--migration",
        type=Path,
        default=None,
        help="Migration SQL path; defaults to migrations/001_moviehub_core.sql",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check migration status without changing the database",
    )

    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        database_path = (
            args.db.expanduser().resolve()
            if args.db
            else get_default_database_path()
        )

        migration_path = (
            args.migration.expanduser().resolve()
            if args.migration
            else get_default_migration_path()
        )

        logger.info("Database: %s", database_path)
        logger.info("Migration: %s", migration_path)

        version = execute_migration(
            database_path=database_path,
            migration_path=migration_path,
            check_only=args.check_only,
        )

        logger.info("Final schema version: %s", version)
        return 0

    except Exception as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

