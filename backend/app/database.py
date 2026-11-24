"""MovieHub-owned SQLite schema and connection management."""

from collections.abc import Generator
from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, CheckConstraint, create_engine, event,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from app.config import settings

Base = declarative_base()
DATABASE_NAME = "movies.db"
CURRENT_SCHEMA_VERSION = 4
REQUIRED_DATABASE_TABLES = {
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
    "movie_metadata_provenance",
    "external_api_cache",
}


class ExternalAPICache(Base):
    """Disposable, bounded response cache for upstream APIs."""

    __tablename__ = "external_api_cache"

    cache_key = Column(String(64), primary_key=True)
    provider = Column(String(32), nullable=False)
    endpoint = Column(String(128), nullable=False)
    params_json = Column(Text, nullable=False)
    response_json = Column(Text, nullable=False)
    fetched_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    last_accessed_at = Column(Integer, nullable=False)
    payload_bytes = Column(Integer, nullable=False)
    hit_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("payload_bytes >= 0", name="ck_external_api_cache_payload_bytes"),
        CheckConstraint("hit_count >= 0", name="ck_external_api_cache_hit_count"),
        Index("ix_external_api_cache_expires_at", "expires_at"),
        Index("ix_external_api_cache_last_accessed_at", "last_accessed_at"),
    )

class DatabaseNotInitializedError(RuntimeError):
    """Raised when API access is attempted before explicit DB initialization."""


def get_db_path() -> str:
    """Return the configured MovieHub database path."""
    return str(Path(settings.data_dir).expanduser().absolute() / "db" / DATABASE_NAME)


def get_database_url() -> str:
    """Build the SQLite URL without creating directories or database files."""
    return f"sqlite:///{Path(get_db_path()).as_posix()}"


def database_is_ready(path: str | Path | None = None) -> bool:
    """Check the required schema through a read-only SQLite connection."""
    database_path = Path(path or get_db_path()).expanduser().resolve()
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return False

    try:
        connection = sqlite3.connect(
            database_path.as_uri() + "?mode=ro",
            uri=True,
            timeout=2,
        )
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not REQUIRED_DATABASE_TABLES.issubset(tables):
                return False

            row = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            return bool(row and row[0] == CURRENT_SCHEMA_VERSION)
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    douban_id = Column(String(32), unique=True, nullable=True, index=True)
    imdb_id = Column(String(32), unique=True, nullable=True, index=True)
    tmdb_id = Column(String(32), unique=True, nullable=True, index=True)
    title = Column(String(256), nullable=False, index=True)
    original_title = Column(String(256), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)
    rating = Column(Float, nullable=True, index=True)
    rating_count = Column(Integer, nullable=False, default=0, index=True)
    type = Column(String(16), nullable=False, default="movie", index=True)
    directors = Column(Text, nullable=False, default="[]")
    actors = Column(Text, nullable=False, default="[]")
    overview = Column(Text, nullable=True)
    douban_url = Column(String(512), nullable=True)
    updated_at = Column(Integer, nullable=True)

    genres = relationship("MovieGenre", back_populates="movie", cascade="all, delete-orphan")
    regions = relationship("MovieRegion", back_populates="movie", cascade="all, delete-orphan")
    posters = relationship("MoviePoster", back_populates="movie", cascade="all, delete-orphan")
    chart_items = relationship("ChartItem", back_populates="movie")
    favorite = relationship("Favorite", back_populates="movie", uselist=False)

    __table_args__ = (
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 10)", name="ck_movies_rating"),
        CheckConstraint("rating_count >= 0", name="ck_movies_rating_count"),
        CheckConstraint("type IN ('movie', 'tv')", name="ck_movies_type"),
        Index("ix_movies_rating_id", "rating", "id"),
        Index("ix_movies_year_id", "year", "id"),
        Index("ix_movies_rating_count_id", "rating_count", "id"),
    )


class Genre(Base):
    __tablename__ = "genres"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False, index=True)
    movie_associations = relationship("MovieGenre", back_populates="genre_obj")


class MovieGenre(Base):
    __tablename__ = "movie_genres"
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    genre_id = Column(Integer, ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)
    movie = relationship("Movie", back_populates="genres")
    genre_obj = relationship("Genre", back_populates="movie_associations")


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False, index=True)
    movie_associations = relationship("MovieRegion", back_populates="region_obj")


class MovieRegion(Base):
    __tablename__ = "movie_regions"
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="CASCADE"), primary_key=True)
    movie = relationship("Movie", back_populates="regions")
    region_obj = relationship("Region", back_populates="movie_associations")


class MoviePoster(Base):
    __tablename__ = "movie_posters"
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    url = Column(String(512), primary_key=True)
    movie = relationship("Movie", back_populates="posters")


class Chart(Base):
    __tablename__ = "lists"
    list_id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(96), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)
    source = Column(String(32), nullable=False, index=True)
    category = Column(String(32), nullable=False, index=True)
    period = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)
    last_updated = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    snapshots = relationship("ChartSnapshot", back_populates="chart", cascade="all, delete-orphan")


class ChartSnapshot(Base):
    __tablename__ = "chart_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    list_id = Column(Integer, ForeignKey("lists.list_id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(String(10), nullable=False)
    imported_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    item_count = Column(Integer, nullable=False, default=0)
    chart = relationship("Chart", back_populates="snapshots")
    items = relationship("ChartItem", back_populates="snapshot", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("list_id", "snapshot_date", name="uq_chart_snapshots_list_date"),
        CheckConstraint("item_count >= 0", name="ck_chart_snapshots_item_count"),
        Index("ix_chart_snapshots_list_id", "list_id"),
        Index("ix_chart_snapshots_snapshot_date", "snapshot_date"),
    )


class ChartItem(Base):
    __tablename__ = "list_items"
    snapshot_id = Column(Integer, ForeignKey("chart_snapshots.id", ondelete="CASCADE"), primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="RESTRICT"), primary_key=True)
    rank = Column(Integer, nullable=False)
    source_rating = Column(Float, nullable=True)
    snapshot = relationship("ChartSnapshot", back_populates="items")
    movie = relationship("Movie", back_populates="chart_items")
    __table_args__ = (
        UniqueConstraint("snapshot_id", "rank", name="uq_list_items_snapshot_rank"),
        CheckConstraint("rank >= 1", name="ck_list_items_rank"),
        CheckConstraint("source_rating IS NULL OR (source_rating >= 0 AND source_rating <= 10)", name="ck_list_items_source_rating"),
        Index("ix_list_items_snapshot_rank", "snapshot_id", "rank"),
        Index("ix_list_items_movie_id", "movie_id"),
    )


class Favorite(Base):
    __tablename__ = "favorites"
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="RESTRICT"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    note = Column(Text, nullable=False, default="")
    movie = relationship("Movie", back_populates="favorite")


class MovieMetadataProvenance(Base):
    """Field-level source and observation history for imported movie metadata."""

    __tablename__ = "movie_metadata_provenance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(String(32), nullable=False)
    source = Column(String(32), nullable=False)
    source_url = Column(String(512), nullable=False, default="")
    observed_at = Column(DateTime, nullable=False)
    value_sha256 = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "movie_id", "field_name", "source", "source_url", "value_sha256",
            name="uq_movie_metadata_provenance_observation",
        ),
        Index("ix_movie_metadata_provenance_movie_field", "movie_id", "field_name"),
        Index("ix_movie_metadata_provenance_observed_at", "observed_at"),
    )


class ImportBatchReceipt(Base):
    """Transactional proof that one Scout import batch committed."""

    __tablename__ = "import_batch_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False)
    batch_number = Column(Integer, nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    processed = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    imported = Column(Integer, nullable=False)
    skipped = Column(Integer, nullable=False)
    errors = Column(Integer, nullable=False)
    last_douban_id = Column(String(32), nullable=False)
    error_records = Column(Text, nullable=False, default="[]")
    committed_at = Column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "batch_number", name="uq_import_batch_receipts_run_batch"),
        CheckConstraint("batch_number >= 1", name="ck_import_batch_receipts_batch"),
        CheckConstraint("processed >= 1 AND processed <= total", name="ck_import_batch_receipts_processed"),
        CheckConstraint("total >= 1", name="ck_import_batch_receipts_total"),
        CheckConstraint("imported >= 0 AND skipped >= 0 AND errors >= 0", name="ck_import_batch_receipts_counters"),
        CheckConstraint("processed = imported + skipped", name="ck_import_batch_receipts_accounting"),
        CheckConstraint("errors <= skipped", name="ck_import_batch_receipts_errors"),
        Index("ix_import_batch_receipts_run_id", "run_id", "batch_number"),
    )


DATABASE_URL = get_database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA cache_size = -20000")
    cursor.execute("PRAGMA mmap_size = 268435456")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)


def get_db() -> Generator[Session, None, None]:
    """Yield a session only after explicit database initialization."""
    db_path = Path(get_db_path())
    if not db_path.is_file():
        raise DatabaseNotInitializedError(
            "MovieHub database is not initialized. "
            "Run 'python -m scripts.init_db' before using the API."
        )

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
