"""MovieHub-owned SQLite schema and connection management."""

from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, CheckConstraint, create_engine, event,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from app.config import settings

Base = declarative_base()
DATABASE_NAME = "movies.db"


class DatabaseNotInitializedError(RuntimeError):
    """Raised when API access is attempted before explicit DB initialization."""


def get_db_path() -> str:
    """Return the configured MovieHub database path."""
    return str(Path(settings.data_dir).expanduser().absolute() / "db" / DATABASE_NAME)


def get_database_url() -> str:
    """Build the SQLite URL without creating directories or database files."""
    return f"sqlite:///{Path(get_db_path()).as_posix()}"


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
