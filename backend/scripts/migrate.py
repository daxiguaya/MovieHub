
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
    python -m scripts.migrate --migration /path/to/002_durable_import_batch_receipts.sql
    python -m scripts.migrate --check-only
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect

from app.database import Base


logger = logging.getLogger("moviehub.migrate")

MIGRATION_VERSION = 5
MIGRATION_FILENAME = "005_imdb_ratings.sql"

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
    "imdb_rating",
    "imdb_rating_count",
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
    "chart_snapshots",
    "list_items",
    "favorites",
    "schema_migrations",
    "import_batch_receipts",
    "movie_metadata_provenance",
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



def validate_orm_schema_contract(database_path: Path) -> None:
    """Require the migrated SQL schema to match the application's ORM contract."""
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
        expected_tables = set(Base.metadata.tables) | {"schema_migrations"}
        actual_tables = set(inspector.get_table_names())
        if actual_tables != expected_tables:
            raise RuntimeError(
                "ORM/database table mismatch: "
                f"ORM-only={sorted(expected_tables-actual_tables)}, "
                f"DB-only={sorted(actual_tables-expected_tables)}"
            )

        for table_name, table in Base.metadata.tables.items():
            actual_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            expected_columns = set(table.columns.keys())
            if actual_columns != expected_columns:
                raise RuntimeError(
                    f"Column mismatch in {table_name}: "
                    f"ORM-only={sorted(expected_columns-actual_columns)}, "
                    f"DB-only={sorted(actual_columns-expected_columns)}"
                )

            expected_indexes = {
                (
                    index.name,
                    tuple(column.name for column in index.columns),
                    bool(index.unique),
                )
                for index in table.indexes
            }
            actual_indexes = {
                (
                    index["name"],
                    tuple(index["column_names"]),
                    bool(index["unique"]),
                )
                for index in inspector.get_indexes(table_name)
            }
            if actual_indexes != expected_indexes:
                raise RuntimeError(
                    f"Index mismatch in {table_name}: "
                    f"missing={sorted(expected_indexes-actual_indexes)}, "
                    f"unexpected={sorted(actual_indexes-expected_indexes)}"
                )

            expected_unique = {
                (constraint.name, tuple(column.name for column in constraint.columns))
                for constraint in table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            actual_unique = {
                (
                    constraint["name"],
                    tuple(constraint["column_names"]),
                )
                for constraint in inspector.get_unique_constraints(table_name)
            }
            if actual_unique != expected_unique:
                raise RuntimeError(
                    f"Unique-constraint mismatch in {table_name}: "
                    f"missing={sorted(expected_unique-actual_unique)}, "
                    f"unexpected={sorted(actual_unique-expected_unique)}"
                )

            expected_foreign_keys = {
                (
                    tuple(element.parent.name for element in constraint.elements),
                    constraint.elements[0].column.table.name,
                    tuple(element.column.name for element in constraint.elements),
                    (constraint.elements[0].ondelete or "").upper(),
                )
                for constraint in table.foreign_key_constraints
            }
            actual_foreign_keys = {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    (foreign_key.get("options", {}).get("ondelete") or "").upper(),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            }
            if actual_foreign_keys != expected_foreign_keys:
                raise RuntimeError(
                    f"Foreign-key mismatch in {table_name}: "
                    f"missing={sorted(expected_foreign_keys-actual_foreign_keys)}, "
                    f"unexpected={sorted(actual_foreign_keys-expected_foreign_keys)}"
                )

            expected_checks = {
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            }
            actual_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            if actual_checks != expected_checks:
                raise RuntimeError(
                    f"Check-constraint mismatch in {table_name}: "
                    f"missing={sorted(expected_checks-actual_checks)}, "
                    f"unexpected={sorted(actual_checks-expected_checks)}"
                )
    finally:
        engine.dispose()


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
        validate_foreign_keys(conn)

    finally:
        conn.close()

    validate_orm_schema_contract(database_path)


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

    # A database that was using WAL may still have -wal/-shm files after a
    # failed migration. Replacing only the main database file while leaving
    # those sidecars behind can cause SQLite to replay stale pages against the
    # restored backup. All migration connections are closed before this point.
    for sidecar in (
        Path(str(database_path) + "-wal"),
        Path(str(database_path) + "-shm"),
        Path(str(database_path) + "-journal"),
    ):
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove SQLite sidecar: %s", sidecar)
            raise

    for sidecar in (
        Path(str(restore_path) + "-wal"),
        Path(str(restore_path) + "-shm"),
        Path(str(restore_path) + "-journal"),
    ):
        sidecar.unlink(missing_ok=True)

    os.replace(restore_path, database_path)

    logger.warning("Original database restored from: %s", backup_path)



@contextmanager
def migration_lock(database_path: Path):
    """Serialize migration/check operations across processes on POSIX hosts."""
    lock_path = Path(str(database_path) + ".migration.lock")
    descriptor = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _execute_migration_locked(
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

    with open_database(database_path) as conn:
        current_version = get_schema_version(conn)

    logger.info("Current schema version: %s", current_version)

    if current_version == 0:
        if check_only:
            logger.info(
                "Check-only mode: database is not initialized; no changes made"
            )
            return 0

        with open_database(database_path) as conn:
            existing_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        if existing_tables:
            raise RuntimeError(
                "Refusing to migrate a non-empty database without a recognized "
                "MovieHub schema version. Initialize a new MovieHub database "
                "with 'python -m scripts.init_db'; Scout and other databases "
                "are never converted or modified."
            )
        raise RuntimeError(
            "MovieHub database has not been initialized. Run "
            "'python -m scripts.init_db' first; this migration only upgrades "
            "an initialized MovieHub schema and never initializes or modifies Scout."
        )
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

    if current_version not in (1, 2, 3, 4):
        raise RuntimeError(
            f"Unsupported starting schema version: {current_version}. "
            "This migration runner upgrades schema versions 1, 2, 3 or 4 to version 5."
        )

    migration_paths = []
    if current_version == 1:
        migration_paths.append(
            migration_path.parent / "002_durable_import_batch_receipts.sql"
        )
    if migration_path.name == MIGRATION_FILENAME and current_version <= 2:
        migration_paths.append(
            migration_path.parent / "003_movie_metadata_provenance.sql"
        )
    if migration_path.name == MIGRATION_FILENAME and current_version <= 3:
        migration_paths.append(
            migration_path.parent / "004_nullable_douban_vote_count.sql"
        )
    migration_paths.append(migration_path)
    migration_sql = []
    for pending_path in migration_paths:
        if not pending_path.is_file():
            raise FileNotFoundError(f"Migration SQL file does not exist: {pending_path}")
        sql = pending_path.read_text(encoding="utf-8").strip()
        if not sql:
            raise RuntimeError(f"Migration SQL file is empty: {pending_path}")
        migration_sql.append((pending_path, sql))

    if check_only:
        logger.info(
            "Check-only mode: %s migration(s) are pending; no changes made",
            len(migration_sql),
        )
        return current_version

    backup_path = create_backup(database_path)
    migration_started = False

    try:
        for pending_path, sql in migration_sql:
            logger.info("Executing migration SQL: %s", pending_path)
            # Each numbered SQL migration owns its explicit transaction.
            conn = open_database(database_path)
            try:
                migration_started = True
                conn.executescript(sql)
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


def execute_migration(
    database_path: Path,
    migration_path: Path,
    check_only: bool = False,
) -> int:
    """Run migration under a process-wide lock for this database file."""
    with migration_lock(database_path):
        return _execute_migration_locked(
            database_path=database_path,
            migration_path=migration_path,
            check_only=check_only,
        )


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
        help="Migration SQL path; defaults to migrations/002_durable_import_batch_receipts.sql",
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

