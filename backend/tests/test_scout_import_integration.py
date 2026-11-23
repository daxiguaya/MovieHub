"""Read-only Douban Scout import integration tests."""

import hashlib
import json
import sqlite3

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    Genre,
    Movie,
    MovieGenre,
    MoviePoster,
    MovieRegion,
    Region,
)
import app.services.import_service as import_service_module


def _create_scout_fixture(path):
    detail = {
        "rating": {"count": 1234},
        "pic": {
            "normal": "https://img.example/poster-small.jpg",
            "large": "https://img.example/poster-large.jpg",
        },
        "cover_url": "https://img.example/poster-cover.jpg",
        "genres": ["剧情", "科幻"],
        "types": ["悬疑"],
        "countries": ["中国大陆"],
        "regions": ["香港"],
        "original_title": "Original Fixture Title",
        "summary": "A Scout fixture overview.",
        "url": "https://movie.douban.com/subject/1234567/",
        "directors": [{"name": "Director One"}],
        "actors": [{"name": "Actor One"}, "Actor Two"],
    }
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE item (
                douban_id TEXT,
                imdb_id TEXT,
                douban_title TEXT,
                year INTEGER,
                rating REAL,
                raw_data TEXT,
                type TEXT,
                update_time INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1234567",
                "tt1234567",
                "Scout Fixture Movie",
                2020,
                8.6,
                json.dumps({"detail": detail}, ensure_ascii=False),
                "movie",
                1790000000,
            ),
        )
        conn.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "7654321",
                None,
                "Scout Fixture TV",
                2022,
                7.9,
                json.dumps(
                    {"detail": {"summary": "TV overview"}},
                    ensure_ascii=False,
                ),
                "tv",
                1790000100,
            ),
        )
        conn.commit()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_scout_import_is_read_only_and_maps_to_moviehub_internal_ids(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout.sqlite"
    target_path = tmp_path / "moviehub.sqlite"
    _create_scout_fixture(source_path)
    source_hash_before = _sha256(source_path)

    engine = create_engine(
        f"sqlite:///{target_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(import_service_module, "SessionLocal", TargetSession)
    monkeypatch.setattr(
        import_service_module.cache_manager,
        "clear",
        lambda: None,
    )

    service = import_service_module.ImportService()
    assert service._run_lock.acquire(blocking=False)

    try:
        service._run_import(source_path, force_full=True)
        assert service.status.status == "completed"

        with TargetSession() as db:
            movie = db.scalar(
                select(Movie).where(Movie.douban_id == "1234567")
            )
            tv = db.scalar(
                select(Movie).where(Movie.douban_id == "7654321")
            )

            assert movie is not None
            assert tv is not None
            assert movie.id != 1234567
            assert tv.id != 7654321
            assert movie.title == "Scout Fixture Movie"
            assert movie.imdb_id == "tt1234567"
            assert movie.year == 2020
            assert movie.rating == 8.6
            assert movie.rating_count == 1234
            assert movie.type == "movie"
            assert movie.original_title == "Original Fixture Title"
            assert movie.overview == "A Scout fixture overview."
            assert movie.douban_url == (
                "https://movie.douban.com/subject/1234567/"
            )
            assert movie.updated_at == 1790000000
            assert json.loads(movie.directors) == ["Director One"]
            assert json.loads(movie.actors) == ["Actor One", "Actor Two"]

            genre_names = set(
                db.scalars(
                    select(Genre.name)
                    .join(MovieGenre, MovieGenre.genre_id == Genre.id)
                    .where(MovieGenre.movie_id == movie.id)
                ).all()
            )
            region_names = set(
                db.scalars(
                    select(Region.name)
                    .join(MovieRegion, MovieRegion.region_id == Region.id)
                    .where(MovieRegion.movie_id == movie.id)
                ).all()
            )
            poster_urls = set(
                db.scalars(
                    select(MoviePoster.url).where(
                        MoviePoster.movie_id == movie.id
                    )
                ).all()
            )

            assert {"剧情", "科幻", "悬疑"} <= genre_names
            assert {"中国大陆", "香港"} <= region_names
            assert poster_urls == {
                "https://img.example/poster-small.jpg",
                "https://img.example/poster-large.jpg",
                "https://img.example/poster-cover.jpg",
            }
            assert tv.overview == "TV overview"

    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()

    # The importer must never write to the external Scout database.
    assert _sha256(source_path) == source_hash_before
    with sqlite3.connect(source_path) as source:
        assert source.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 2


def test_incremental_import_skips_unchanged_rows_but_force_full_reprocesses(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-incremental.sqlite"
    target_path = tmp_path / "moviehub-incremental.sqlite"
    _create_scout_fixture(source_path)

    engine = create_engine(
        f"sqlite:///{target_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(import_service_module, "SessionLocal", TargetSession)
    monkeypatch.setattr(import_service_module.cache_manager, "clear", lambda: None)

    service = import_service_module.ImportService()

    def run(force_full):
        assert service._run_lock.acquire(blocking=False)
        try:
            service._run_import(source_path, force_full=force_full)
            assert service.status.status == "completed"
        finally:
            if service._run_lock.locked():
                service._run_lock.release()

    run(force_full=True)
    with TargetSession() as db:
        movie = db.scalar(select(Movie).where(Movie.douban_id == "1234567"))
        assert movie.title == "Scout Fixture Movie"

    # Change source metadata without advancing Scout's update_time. An
    # incremental run must not rewrite a record already imported at this time.
    with sqlite3.connect(source_path) as conn:
        row = conn.execute(
            "SELECT raw_data FROM item WHERE douban_id = '1234567'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["detail"]["summary"] = "Changed without a newer source timestamp"
        conn.execute(
            "UPDATE item SET raw_data = ? WHERE douban_id = '1234567'",
            (json.dumps(payload, ensure_ascii=False),),
        )

    run(force_full=False)
    with TargetSession() as db:
        movie = db.scalar(select(Movie).where(Movie.douban_id == "1234567"))
        assert movie.overview == "A Scout fixture overview."

    run(force_full=True)
    with TargetSession() as db:
        movie = db.scalar(select(Movie).where(Movie.douban_id == "1234567"))
        assert movie.overview == "Changed without a newer source timestamp"

    engine.dispose()
