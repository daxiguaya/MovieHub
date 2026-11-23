"""Initialize a brand-new, independent MovieHub SQLite database.

Run from the backend directory:
    python -m scripts.init_db
    python -m scripts.init_db --db /path/to/movies.db
"""

import argparse
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.services.chart_init_service import initialize_chart_definitions

logger = logging.getLogger("moviehub.init_db")
MIGRATION_VERSION = 2
REQUIRED_TABLES = {
    "schema_migrations",
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
    "import_batch_receipts",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a new MovieHub SQLite database"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Database path; defaults to MOVIEHUB_DATA_DIR/db/movies.db",
    )
    parser.add_argument(
        "--migration",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "migrations"
        / "001_moviehub_core.sql",
        help="Initial schema SQL file",
    )
    return parser.parse_args()


def validate_database(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        conn.execute("PRAGMA foreign_keys=ON")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"Foreign-key violations: {fk_errors[:10]}")

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"Missing required tables: {sorted(missing)}")

        version = conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]
        if version != MIGRATION_VERSION:
            raise RuntimeError(
                f"Expected schema version {MIGRATION_VERSION}, got {version}"
            )
    finally:
        conn.close()

    # Compare the declared ORM table/column contract with the SQL-created DB.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        inspector = inspect(engine)
        orm_tables = set(Base.metadata.tables) | {"schema_migrations"}
        db_tables = set(inspector.get_table_names())
        if orm_tables != db_tables:
            raise RuntimeError(
                f"ORM/database table mismatch: ORM-only={sorted(orm_tables-db_tables)}, "
                f"DB-only={sorted(db_tables-orm_tables)}"
            )

        for table_name, table in Base.metadata.tables.items():
            orm_columns = set(table.columns.keys())
            db_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            if orm_columns != db_columns:
                raise RuntimeError(
                    f"Column mismatch in {table_name}: "
                    f"ORM-only={sorted(orm_columns-db_columns)}, "
                    f"DB-only={sorted(db_columns-orm_columns)}"
                )
    finally:
        engine.dispose()


def _remove_sqlite_files(path: Path) -> None:
    """Remove a temporary SQLite database and any WAL sidecars."""
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove temporary database file: %s", candidate)


def initialize(path: Path, migration_path: Path) -> None:
    """Build and validate a temporary database, then atomically publish it."""
    path = path.expanduser().resolve()
    migration_path = migration_path.expanduser().resolve()

    if not migration_path.is_file():
        raise FileNotFoundError(f"Initial schema not found: {migration_path}")

    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.stat().st_size > 0:
        probe = sqlite3.connect(str(path))
        try:
            existing = probe.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        finally:
            probe.close()
        if existing:
            raise RuntimeError(
                "Refusing to initialize a non-empty database. "
                "This command only initializes a new MovieHub database; "
                "it will not convert or modify Douban Scout."
            )

    sql = migration_path.read_text(encoding="utf-8").strip()
    if not sql:
        raise RuntimeError("Initial schema SQL is empty")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".initializing",
        dir=str(path.parent),
    )
    os.close(fd)
    temporary_path = Path(temporary_name)

    try:
        followup_migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "002_durable_import_batch_receipts.sql"
        )
        if not followup_migration.is_file():
            raise FileNotFoundError(
                f"Required follow-up migration not found: {followup_migration}"
            )
        followup_sql = followup_migration.read_text(encoding="utf-8").strip()
        if not followup_sql:
            raise RuntimeError("Follow-up migration SQL is empty")

        conn = sqlite3.connect(str(temporary_path), timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(sql)
            conn.executescript(followup_sql)
        finally:
            conn.close()

        validate_database(temporary_path)

        # Enable WAL only after successful schema creation and validation.
        conn = sqlite3.connect(str(temporary_path), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()

        # Seed built-in chart definitions without overwriting user settings.
        engine = create_engine(
            f"sqlite:///{temporary_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        try:
            Session = sessionmaker(
                bind=engine, autoflush=False, expire_on_commit=False
            )
            with Session() as db:
                result = initialize_chart_definitions(db)
            logger.info("Built-in charts initialized: %s", result)
        finally:
            engine.dispose()

        validate_database(temporary_path)

        # All SQLite/SQLAlchemy connections are closed before publication.
        os.replace(temporary_path, path)
        logger.info("MovieHub database initialized and validated: %s", path)

    except Exception:
        _remove_sqlite_files(temporary_path)
        raise


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    database_path = args.db or (
        Path(settings.data_dir).expanduser().absolute() / "db" / "movies.db"
    )
    try:
        initialize(database_path, args.migration)
        return 0
    except Exception:
        logger.exception("MovieHub database initialization failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
