"""Read-only Douban Scout import integration tests."""

import hashlib
import json
import sqlite3

import pytest

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

    # A strictly newer source timestamp must be picked up by an incremental run.
    with sqlite3.connect(source_path) as conn:
        row = conn.execute(
            "SELECT raw_data FROM item WHERE douban_id = '1234567'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["detail"]["summary"] = "Changed with a newer source timestamp"
        conn.execute(
            "UPDATE item SET raw_data = ?, update_time = update_time + 1 "
            "WHERE douban_id = '1234567'",
            (json.dumps(payload, ensure_ascii=False),),
        )

    run(force_full=False)
    with TargetSession() as db:
        movie = db.scalar(select(Movie).where(Movie.douban_id == "1234567"))
        assert movie.overview == "Changed with a newer source timestamp"

    engine.dispose()


def test_import_preserves_enriched_fields_and_does_not_delete_absent_scout_rows(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-merge.sqlite"
    target_path = tmp_path / "moviehub-merge.sqlite"
    _create_scout_fixture(source_path)

    with sqlite3.connect(source_path) as source:
        source.execute(
            "UPDATE item SET raw_data = ? WHERE douban_id = '1234567'",
            (json.dumps({"detail": {}}, ensure_ascii=False),),
        )

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

    with TargetSession() as db:
        genre = Genre(name="Drama")
        region = Region(name="Japan")
        movie = Movie(
            douban_id="1234567",
            title="Previously enriched title",
            year=1999,
            rating=9.4,
            rating_count=9000,
            type="movie",
            original_title="Previously enriched original title",
            directors='["Enriched Director"]',
            actors='["Enriched Actor"]',
            overview="Previously enriched overview",
            douban_url="https://movie.douban.com/subject/1234567/",
            updated_at=1790000000,
        )
        db.add_all([genre, region, movie])
        db.flush()
        db.add_all([
            MovieGenre(movie_id=movie.id, genre_id=genre.id),
            MovieRegion(movie_id=movie.id, region_id=region.id),
            MoviePoster(
                movie_id=movie.id,
                url="https://img1.doubanio.com/view/photo/enriched.jpg",
            ),
        ])
        db.commit()

    service = import_service_module.ImportService()

    def run(force_full):
        assert service._run_lock.acquire(blocking=False)
        service._run_import(source_path, force_full=force_full)
        assert service.status.status == "completed"

    run(force_full=True)
    with TargetSession() as db:
        movie = db.scalar(select(Movie).where(Movie.douban_id == "1234567"))
        assert movie.title == "Scout Fixture Movie"
        assert movie.year == 2020
        assert movie.rating == 8.6
        assert movie.rating_count == 9000
        assert movie.original_title == "Previously enriched original title"
        assert movie.directors == '["Enriched Director"]'
        assert movie.actors == '["Enriched Actor"]'
        assert movie.overview == "Previously enriched overview"
        assert db.scalar(
            select(Genre.name)
            .join(MovieGenre, MovieGenre.genre_id == Genre.id)
            .where(MovieGenre.movie_id == movie.id)
        ) == "Drama"
        assert db.scalar(
            select(Region.name)
            .join(MovieRegion, MovieRegion.region_id == Region.id)
            .where(MovieRegion.movie_id == movie.id)
        ) == "Japan"
        assert db.scalar(
            select(MoviePoster.url).where(MoviePoster.movie_id == movie.id)
        ) == "https://img1.doubanio.com/view/photo/enriched.jpg"

    # Deleting a row from Scout is not a deletion instruction for MovieHub.
    with sqlite3.connect(source_path) as source:
        source.execute("DELETE FROM item WHERE douban_id = '7654321'")

    run(force_full=True)
    with TargetSession() as db:
        assert db.scalar(
            select(Movie).where(Movie.douban_id == "7654321")
        ) is not None

    engine.dispose()


def test_batched_import_keeps_committed_batches_and_retry_completes(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-batches.sqlite"
    target_path = tmp_path / "moviehub-batches.sqlite"
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
    service._BATCH_SIZE = 1
    original_ensure_genres = service._ensure_genres
    calls = {"count": 0}

    def fail_on_second_batch(db):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated second-batch failure")
        return original_ensure_genres(db)

    monkeypatch.setattr(service, "_ensure_genres", fail_on_second_batch)
    assert service._run_lock.acquire(blocking=False)
    service._run_import(source_path, force_full=False)
    assert service.status.status == "failed"

    with TargetSession() as db:
        assert db.scalar(
            select(Movie).where(Movie.douban_id == "1234567")
        ) is not None
        assert db.scalar(
            select(Movie).where(Movie.douban_id == "7654321")
        ) is None

    monkeypatch.setattr(service, "_ensure_genres", original_ensure_genres)
    assert service._run_lock.acquire(blocking=False)
    service._run_import(source_path, force_full=False)
    assert service.status.status == "completed"

    with TargetSession() as db:
        assert db.scalar(
            select(Movie).where(Movie.douban_id == "1234567")
        ) is not None
        assert db.scalar(
            select(Movie).where(Movie.douban_id == "7654321")
        ) is not None

    engine.dispose()


def test_scout_import_uses_one_consistent_source_snapshot(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-wal-snapshot.sqlite"
    target_path = tmp_path / "moviehub-wal-snapshot.sqlite"
    _create_scout_fixture(source_path)
    with sqlite3.connect(source_path) as source:
        source.execute("PRAGMA journal_mode=WAL")

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

    original_validate = import_service_module.ImportService._validate_source
    inserted = {"value": False}

    def validate_then_write(
        source_conn,
        reject_duplicate_ids=False,
        reject_invalid_identity=False,
    ):
        original_validate(
            source_conn,
            reject_duplicate_ids,
            reject_invalid_identity,
        )
        if not inserted["value"]:
            with sqlite3.connect(source_path, timeout=5) as writer:
                writer.execute(
                    "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "8888888", None, "Concurrent Scout Write", 2024, 7.5,
                        "{}", "movie", 1800000200,
                    ),
                )
            inserted["value"] = True

    monkeypatch.setattr(
        import_service_module.ImportService,
        "_validate_source",
        staticmethod(validate_then_write),
    )

    service = import_service_module.ImportService()
    assert service._run_lock.acquire(blocking=False)
    try:
        service._run_import(source_path, force_full=True)
        assert service.status.status == "completed"
        assert service.status.total == 2
        assert service.status.processed == 2
        with TargetSession() as db:
            assert db.query(Movie).count() == 2
        with sqlite3.connect(source_path) as source:
            assert source.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 3
    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()


def test_scout_import_reports_record_errors_in_completed_status(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-record-error.sqlite"
    target_path = tmp_path / "moviehub-record-error.sqlite"
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
    original_upsert = service._upsert_source_row

    def fail_one_record(db, row, genre_map, region_map, force_full=False):
        if row["douban_id"] == "1234567":
            raise RuntimeError("simulated malformed source record")
        return original_upsert(db, row, genre_map, region_map, force_full)

    monkeypatch.setattr(service, "_upsert_source_row", fail_one_record)
    assert service._run_lock.acquire(blocking=False)
    try:
        service._run_import(source_path, force_full=True)
        status = service.status
        assert status.status == "completed"
        assert status.errors == 1
        assert "record errors 1" in status.message

        with TargetSession() as db:
            assert db.scalar(
                select(Movie).where(Movie.douban_id == "1234567")
            ) is None
            assert db.scalar(
                select(Movie).where(Movie.douban_id == "7654321")
            ) is not None
    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()


def test_scout_import_processes_synthetic_catalogue_across_multiple_batches(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-large-fixture.sqlite"
    target_path = tmp_path / "moviehub-large-fixture.sqlite"
    _create_scout_fixture(source_path)

    synthetic_count = 1000
    with sqlite3.connect(source_path) as source:
        source.executemany(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(8000000 + index),
                    None,
                    f"Synthetic Movie {index}",
                    1980 + (index % 45),
                    6.0 + (index % 40) / 10,
                    json.dumps(
                        {"detail": {"summary": f"Synthetic overview {index}"}},
                        ensure_ascii=False,
                    ),
                    "movie",
                    1800000000 + index,
                )
                for index in range(synthetic_count)
            ],
        )

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
    service._BATCH_SIZE = 200
    assert service._run_lock.acquire(blocking=False)
    try:
        service._run_import(source_path, force_full=True)
        assert service.status.status == "completed"
        assert service.status.processed == synthetic_count + 2
        assert service.status.total == synthetic_count + 2
        assert service.status.percentage == 100.0

        with TargetSession() as db:
            assert db.query(Movie).count() == synthetic_count + 2
            assert db.scalar(
                select(Movie).where(Movie.douban_id == "8000999")
            ).title == "Synthetic Movie 999"
    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()

def test_scout_import_rejects_invalid_ratings_and_implausible_years(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-invalid-numbers.sqlite"
    target_path = tmp_path / "moviehub-invalid-numbers.sqlite"
    _create_scout_fixture(source_path)

    with sqlite3.connect(source_path) as source:
        source.execute(
            "UPDATE item SET rating = ?, year = ? WHERE douban_id = '1234567'",
            (10.5, 1800),
        )
        source.execute(
            "UPDATE item SET rating = ?, year = ? WHERE douban_id = '7654321'",
            (float("inf"), 2201),
        )

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

    with TargetSession() as db:
        existing = Movie(
            douban_id="1234567",
            title="Existing enriched movie",
            year=1999,
            rating=9.2,
            rating_count=100,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(existing)
        db.commit()

    service = import_service_module.ImportService()
    assert service._run_lock.acquire(blocking=False)
    try:
        service._run_import(source_path, force_full=True)
        assert service.status.status == "completed"

        with TargetSession() as db:
            existing = db.scalar(
                select(Movie).where(Movie.douban_id == "1234567")
            )
            new_tv = db.scalar(
                select(Movie).where(Movie.douban_id == "7654321")
            )
            # Invalid source values must not erase previously valid metadata.
            assert existing.year == 1999
            assert existing.rating == 9.2
            # Invalid values on a new row remain absent, not persisted.
            assert new_tv.year is None
            assert new_tv.rating is None
    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()


def test_scout_integer_normalization_rejects_booleans_and_fractional_values():
    service = import_service_module.ImportService()
    assert service._safe_int(True, default=7) == 7
    assert service._safe_int(2020.5, default=7) == 7
    assert service._safe_int("2020", default=7) == 2020



def test_scout_import_rejects_duplicate_douban_ids_before_writing(tmp_path):
    source_path = tmp_path / "scout-duplicate-ids.sqlite"
    _create_scout_fixture(source_path)

    with sqlite3.connect(source_path) as source:
        source.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1234567",
                None,
                "Conflicting duplicate record",
                2021,
                7.0,
                "{}",
                "movie",
                1790000200,
            ),
        )

    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        with pytest.raises(ValueError, match="duplicate Douban IDs: 1234567"):
            import_service_module.ImportService._validate_source(
                source,
                reject_duplicate_ids=True,
                reject_invalid_identity=True,
            )
    finally:
        source.close()


def test_scout_import_rejects_invalid_identity_fields_before_target_writes(tmp_path):
    source_path = tmp_path / "scout-invalid-identity.sqlite"
    _create_scout_fixture(source_path)

    with sqlite3.connect(source_path) as source:
        source.execute(
            "UPDATE item SET douban_id = NULL WHERE douban_id = '1234567'"
        )

    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        with pytest.raises(
            ValueError,
            match="invalid Douban ID or empty title: rowid=",
        ):
            import_service_module.ImportService._validate_source(
                source,
                reject_duplicate_ids=True,
                reject_invalid_identity=True,
            )
    finally:
        source.close()


def test_scout_import_rejects_non_numeric_ids_and_blank_titles(tmp_path):
    source_path = tmp_path / "scout-invalid-title.sqlite"
    _create_scout_fixture(source_path)

    with sqlite3.connect(source_path) as source:
        source.execute(
            "UPDATE item SET douban_id = ?, douban_title = ? "
            "WHERE douban_id = '1234567'",
            ("tt1234567", "   "),
        )

    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        with pytest.raises(
            ValueError,
            match="invalid Douban ID or empty title",
        ):
            import_service_module.ImportService._validate_source(
                source,
                reject_duplicate_ids=True,
                reject_invalid_identity=True,
            )
    finally:
        source.close()



def test_import_preview_classifies_new_updates_and_unchanged_without_writes(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "scout-preview.sqlite"
    target_path = tmp_path / "moviehub-preview.sqlite"
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
    with TargetSession() as db:
        db.add(Movie(
            douban_id="1234567",
            title="Existing movie",
            type="movie",
            updated_at=1790000000,
        ))
        db.commit()
    target_hash_before = _sha256(target_path)

    service = import_service_module.ImportService()
    preview = service.preview_import(source_path)
    forced = service.preview_import(source_path, force_full=True)

    assert preview["read_only"] is True
    assert preview["summary"] == {
        "source_records": 2,
        "target_records_checked": 1,
        "new_records": 1,
        "update_candidates": 0,
        "unchanged_skips": 1,
        "would_write": 1,
        "invalid_years": 0,
        "invalid_ratings": 0,
    }
    assert preview["decision"] == "ready_for_import"
    assert forced["summary"]["update_candidates"] == 1
    assert forced["summary"]["unchanged_skips"] == 0
    assert forced["summary"]["would_write"] == 2
    assert _sha256(source_path) == source_hash_before
    assert _sha256(target_path) == target_hash_before

    engine.dispose()


def test_import_preview_rejects_invalid_source_before_target_reads(tmp_path, monkeypatch):
    source_path = tmp_path / "scout-invalid-preview.sqlite"
    _create_scout_fixture(source_path)
    with sqlite3.connect(source_path) as source:
        source.execute("UPDATE item SET douban_id = NULL WHERE douban_id = '1234567'")
        source.commit()

    def target_must_not_be_opened():
        raise AssertionError("target must not be queried when source validation fails")

    monkeypatch.setattr(import_service_module, "SessionLocal", target_must_not_be_opened)
    with pytest.raises(ValueError, match="invalid Douban ID"):
        import_service_module.ImportService().preview_import(source_path)


def test_import_writes_durable_run_and_batch_journal(tmp_path, monkeypatch):
    from app.services.import_journal import (
        get_import_journal_path,
        read_import_events,
    )

    source_path = tmp_path / "scout-journal.sqlite"
    target_path = tmp_path / "moviehub-journal.sqlite"
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
    monkeypatch.setattr(
        import_service_module.cache_manager,
        "clear",
        lambda: None,
    )
    service = import_service_module.ImportService()
    service._BATCH_SIZE = 1
    assert service._run_lock.acquire(blocking=False)
    try:
        service._run_import(source_path, force_full=True, run_id="journal-test-run")
    finally:
        # _run_import owns and releases the lock.
        if service._run_lock.locked():
            service._run_lock.release()

    journal_path = get_import_journal_path(TargetSession)
    events = read_import_events(journal_path)
    assert journal_path.is_file()
    assert journal_path.stat().st_mode & 0o777 == 0o600
    assert [event["event"] for event in events] == [
        "run_started",
        "batch_committed",
        "batch_committed",
        "run_completed",
    ]
    batches = [event for event in events if event["event"] == "batch_committed"]
    assert [event["processed"] for event in batches] == [1, 2]
    assert batches[-1]["last_douban_id"] == "7654321"
    assert events[-1]["run_id"] == "journal-test-run"
    assert events[-1]["imported"] == 2
    engine.dispose()


def test_import_journal_ignores_incomplete_trailing_record(tmp_path):
    from app.services.import_journal import read_import_events

    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        '{"event":"run_started","run_id":"a"}\n{"event":"batch_committed"',
        encoding="utf-8",
    )
    assert read_import_events(journal) == [
        {"event": "run_started", "run_id": "a"}
    ]
