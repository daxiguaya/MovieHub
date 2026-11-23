
"""MovieHub database models and SQLite connection management."""

from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from app.config import settings


Base = declarative_base()

DATABASE_NAME = "movies.db"

FTS_TABLE_NAME = "movie_search"

FTS_CREATE_TABLE_SQL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE_NAME} USING "
    "fts5("
    "title,"
    "original_title,"
    "content='movies',"
    "content_rowid='id',"
    "tokenize='trigram'"
    ")"
)

FTS_REBUILD_SQL = (
    f"INSERT INTO {FTS_TABLE_NAME}({FTS_TABLE_NAME}) VALUES ('rebuild')"
)

FTS_INSERT_ALL_SQL = (
    f"INSERT INTO {FTS_TABLE_NAME}({FTS_TABLE_NAME}) VALUES ('rebuild')"
)


def get_db_path() -> str:
    """Return the absolute path of the MovieHub SQLite database."""
    return str(
        (Path(settings.data_dir).expanduser().absolute() / "db" / DATABASE_NAME)
    )


def get_database_url() -> str:
    """Build the writable SQLite connection URL."""
    db_path = Path(get_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


class Movie(Base):
    """Movie or TV-series metadata."""

    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Douban ID is the stable external identity.
    douban_id = Column(String(32), unique=True, nullable=True, index=True)

    imdb_id = Column(String(32), nullable=True, index=True)
    tmdb_id = Column(String(32), nullable=True, index=True)

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

    genres = relationship(
        "MovieGenre",
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    regions = relationship(
        "MovieRegion",
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    posters = relationship(
        "MoviePoster",
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    chart_items = relationship(
        "ChartItem",
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    favorite = relationship(
        "Favorite",
        back_populates="movie",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_movies_rating_id", "rating", "id"),
        Index("ix_movies_year_id", "year", "id"),
        Index("ix_movies_rating_count_id", "rating_count", "id"),
    )


class Genre(Base):
    """Normalized movie genre."""

    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False, index=True)

    movie_associations = relationship(
        "MovieGenre",
        back_populates="genre_obj",
    )


class MovieGenre(Base):
    """Movie-to-genre association."""

    __tablename__ = "movie_genres"

    movie_id = Column(
        Integer,
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    genre_id = Column(
        Integer,
        ForeignKey("genres.id", ondelete="CASCADE"),
        primary_key=True,
    )

    movie = relationship("Movie", back_populates="genres")
    genre_obj = relationship("Genre", back_populates="movie_associations")


class Region(Base):
    """Normalized production region."""

    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False, index=True)

    movie_associations = relationship(
        "MovieRegion",
        back_populates="region_obj",
    )


class MovieRegion(Base):
    """Movie-to-region association."""

    __tablename__ = "movie_regions"

    movie_id = Column(
        Integer,
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    region_id = Column(
        Integer,
        ForeignKey("regions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    movie = relationship("Movie", back_populates="regions")
    region_obj = relationship("Region", back_populates="movie_associations")


class MoviePoster(Base):
    """Poster URLs associated with a movie."""

    __tablename__ = "movie_posters"

    movie_id = Column(
        Integer,
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    url = Column(String(512), primary_key=True)

    movie = relationship("Movie", back_populates="posters")


class Chart(Base):
    """A named chart/list from an external source."""

    __tablename__ = "lists"

    id = Column(Integer, primary_key=True, autoincrement=True)

    slug = Column(String(96), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)

    source = Column(String(32), nullable=False, index=True)
    category = Column(String(32), nullable=False, index=True)
    period = Column(String(32), nullable=True)

    description = Column(Text, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)

    last_updated = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    items = relationship(
        "ChartItem",
        back_populates="chart",
        cascade="all, delete-orphan",
    )


class ChartItem(Base):
    """A movie's position in a dated chart snapshot."""

    __tablename__ = "list_items"

    list_id = Column(
        Integer,
        ForeignKey("lists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snapshot_date = Column(String(10), primary_key=True)
    douban_id = Column(
        String(32),
        ForeignKey("movies.douban_id", ondelete="CASCADE"),
        primary_key=True,
    )

    rank = Column(Integer, nullable=False)
    source_rating = Column(Float, nullable=True)

    chart = relationship("Chart", back_populates="items")
    movie = relationship("Movie", back_populates="chart_items")

    __table_args__ = (
        UniqueConstraint(
            "list_id",
            "snapshot_date",
            "rank",
            name="uq_list_snapshot_rank",
        ),
        Index(
            "ix_list_items_snapshot_rank",
            "list_id",
            "snapshot_date",
            "rank",
        ),
    )


class Favorite(Base):
    """User's locally stored movie favorites."""

    __tablename__ = "favorites"

    douban_id = Column(
        String(32),
        ForeignKey("movies.douban_id", ondelete="CASCADE"),
        primary_key=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    note = Column(Text, nullable=True)

    movie = relationship("Movie", back_populates="favorite")


# ---------------------------------------------------------------------------
# SQLite engine
# ---------------------------------------------------------------------------

DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,
    },
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Configure SQLite connection behavior."""
    cursor = dbapi_connection.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.execute("PRAGMA synchronous = NORMAL")

    # Keep the per-connection SQLite page cache modest.
    cursor.execute("PRAGMA cache_size = -20000")

    # Avoid excessive memory mapping on a small NAS.
    cursor.execute("PRAGMA mmap_size = 268435456")

    cursor.close()


# Set WAL once when the engine is initialized.
# WAL allows readers to continue while a writer commits a transaction.
with engine.connect() as _connection:
    _connection.exec_driver_sql("PRAGMA journal_mode = WAL")


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

