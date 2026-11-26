"""Protected favorites API integration tests using a temporary MovieHub database."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.routers import discovery, favorites as favorites_router
from app.config import settings
from scripts.init_db import initialize


def test_favorites_use_internal_movie_ids_and_are_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")

    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    with TargetSession() as db:
        movie = database.Movie(
            douban_id="987654",
            title="Favorites Fixture",
            year=2024,
            rating=8.2,
            rating_count=1200,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        internal_movie_id = movie.id

    headers = {"X-API-Key": "favorites-test-key"}
    try:
        with TestClient(main_module.app) as client:
            assert client.get("/api/favorites").status_code == 401
            assert client.put(
                f"/api/favorites/{internal_movie_id}",
                json={"note": "rewatch"},
            ).status_code == 401

            first = client.put(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
                json={"note": "rewatch"},
            )
            second = client.put(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
                json={"note": "rewatch later"},
            )
            listing = client.get("/api/favorites", headers=headers)
            wrong_identifier = client.put(
                "/api/favorites/987654",
                headers=headers,
                json={"note": ""},
            )

            removed = client.delete(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
            )
            empty_listing = client.get("/api/favorites", headers=headers)
            missing_remove = client.delete(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
            )

        assert first.status_code == 200
        assert first.json()["movie"]["id"] == internal_movie_id
        assert first.json()["movie"]["douban_id"] == "987654"
        assert first.json()["note"] == "rewatch"

        assert second.status_code == 200
        assert second.json()["note"] == "rewatch later"
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["movie"]["id"] == internal_movie_id
        assert listing.json()[0]["note"] == "rewatch later"

        # A provider ID is not accepted as a favorite key.
        assert wrong_identifier.status_code == 404

        assert removed.status_code == 204
        assert empty_listing.status_code == 200
        assert empty_listing.json() == []
        assert missing_remove.status_code == 404

        with TargetSession() as db:
            assert db.scalars(select(database.Favorite)).all() == []
    finally:
        engine.dispose()



def test_online_favorite_links_existing_chart_movie_by_imdb_without_creating_catalogue_rows(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="123457",
            imdb_id="tt7654321",
            title="Existing Chart Movie",
            year=2024,
            rating=8.2,
            rating_count=200,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id
        before_count = db.query(database.Movie).count()

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(main_module.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery.provider_response_cache, "save_favorite", lambda media_type, provider_id, snapshot, note="": {
        "provider": "tmdb", "media_type": media_type, "provider_id": provider_id,
        "snapshot": snapshot, "note": note, "created_at": 1, "updated_at": 1
    })
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite",
        lambda media_type, provider_id: True,
    )

    try:
        with TestClient(main_module.app) as client:
            response = client.put(
                "/api/favorites/external/movie/900",
                headers={"X-API-Key": "favorites-test-key"},
                json={"snapshot": {
                    "title": "Online Search Title",
                    "year": 2024,
                    "imdb_id": "tt7654321",
                }},
            )
            listing = client.get(
                "/api/favorites",
                headers={"X-API-Key": "favorites-test-key"},
            )
        assert response.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["movie"]["id"] == movie_id
        assert listing.json()[0]["movie"]["title"] == "Existing Chart Movie"
        with TargetSession() as db:
            assert db.query(database.Movie).count() == before_count
            assert db.get(database.Favorite, movie_id) is not None
    finally:
        engine.dispose()


def test_tmdb_favorite_status_and_removal_include_linked_chart_favorites(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="123456",
            imdb_id="tt1234567",
            tmdb_id="42",
            title="Linked Fixture",
            year=2024,
            rating=8.1,
            rating_count=100,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.flush()
        db.add(database.Favorite(movie_id=movie.id))
        db.commit()

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(main_module.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        discovery.provider_response_cache,
        "has_favorite",
        lambda media_type, provider_id: provider_id == 99,
    )
    monkeypatch.setattr(
        discovery.provider_response_cache,
        "delete_favorite",
        lambda media_type, provider_id: False,
    )

    headers = {"X-API-Key": "favorites-test-key"}
    try:
        with TestClient(main_module.app) as client:
            unauthorized = client.get("/api/favorites/external/status/movie/42")
            linked = client.get(
                "/api/favorites/external/status/movie/42",
                params={"imdb_id": "tt1234567"},
                headers=headers,
            )
            external = client.get(
                "/api/discovery/favorites/status/movie/99",
                headers=headers,
            )
            removed = client.delete(
                "/api/favorites/external/movie/42",
                params={"imdb_id": "tt1234567"},
                headers=headers,
            )

        assert unauthorized.status_code == 401
        assert linked.status_code == 200
        assert linked.json() == {"is_favorite": True}
        assert external.status_code == 200
        assert external.json() == {"is_favorite": True}
        assert removed.status_code == 204
        with TargetSession() as db:
            assert db.scalars(select(database.Favorite)).all() == []
    finally:
        engine.dispose()



def test_external_favorites_endpoint_resolves_imdb_ids_and_attaches_local_ratings(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)

    favorites = [{
        "provider": "tmdb",
        "media_type": "movie",
        "provider_id": 278,
        "snapshot": {
            "title": "肖申克的救赎",
            "original_title": "The Shawshank Redemption",
            "rating": 6.0,
            "rating_count": 5,
            "imdb_id": None,
            "imdb_rating": None,
            "imdb_rating_count": None,
        },
        "note": "",
        "created_at": 1,
        "updated_at": 1,
    }]
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "list_favorites",
        lambda: favorites,
    )

    async def fake_get_json(endpoint, params=None, ttl=900):
        if endpoint == "/movie/278/external_ids":
            return {"id": 278, "imdb_id": "tt0111161"}
        if endpoint == "/movie/278":
            return {
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "vote_average": 9.3,
                "vote_count": 3000000,
            }
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(favorites_router.tmdb_client, "get_json", fake_get_json)
    monkeypatch.setattr(
        favorites_router,
        "lookup_ratings",
        lambda ids: {"tt0111161": (9.3, 3000000)},
    )

    try:
        with TestClient(main_module.app) as client:
            response = client.get(
                "/api/favorites/external",
                headers={"X-API-Key": "favorites-test-key"},
            )
        assert response.status_code == 200
        item = response.json()[0]
        assert item["snapshot"]["imdb_id"] == "tt0111161"
        assert item["snapshot"]["imdb_rating"] == 9.3
        assert item["snapshot"]["imdb_rating_count"] == 3000000
        assert item["snapshot"]["rating"] == 9.3
        assert item["snapshot"]["rating_count"] == 3000000
    finally:
        engine.dispose()


def test_linked_external_favorite_cleanup_failure_is_reported_and_retryable(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="123458",
            imdb_id="tt7654322",
            title="Retryable Linked Movie",
            year=2024,
            rating=8.2,
            rating_count=200,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(discovery.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)

    cleanup_calls = 0

    def flaky_delete(media_type, provider_id):
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError("discovery database temporarily unavailable")
        return True

    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite",
        flaky_delete,
    )
    headers = {"X-API-Key": "favorites-test-key"}
    payload = {"snapshot": {
        "title": "Retryable Linked Movie",
        "year": 2024,
        "imdb_id": "tt7654322",
    }}
    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as client:
            first = client.put(
                "/api/favorites/external/movie/901",
                headers=headers,
                json=payload,
            )
            # The local write committed, but the failed cross-database cleanup
            # must not be reported as a successful complete operation.
            assert first.status_code == 500

            retry = client.put(
                "/api/favorites/external/movie/901",
                headers=headers,
                json=payload,
            )

        assert retry.status_code == 200
        assert retry.json() == {"linked_movie_id": movie_id, "is_favorite": True}
        assert cleanup_calls == 2
        with TargetSession() as db:
            assert db.get(database.Favorite, movie_id) is not None
    finally:
        engine.dispose()


def test_adding_local_favorite_cleans_exact_external_tmdb_favorite_and_retries(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="123459",
            tmdb_id="902",
            imdb_id="tt7654324",
            title="Local Favorite Retry",
            year=2024,
            rating=8.2,
            rating_count=200,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "backup_daily",
        lambda *args, **kwargs: None,
    )

    cleanup_calls = []

    def flaky_delete(media_type, provider_id):
        cleanup_calls.append((media_type, provider_id))
        if len(cleanup_calls) == 1:
            raise OSError("discovery database temporarily unavailable")
        return True

    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite",
        flaky_delete,
    )
    imdb_cleanup_calls = []
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite_by_imdb",
        lambda media_type, imdb_id, title, original_title, year: (
            imdb_cleanup_calls.append((media_type, imdb_id, title, original_title, year))
            or False
        ),
    )

    headers = {"X-API-Key": "favorites-test-key"}
    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as client:
            first = client.put(
                f"/api/favorites/{movie_id}",
                headers=headers,
                json={"note": "local"},
            )
            retry = client.put(
                f"/api/favorites/{movie_id}",
                headers=headers,
                json={"note": "local"},
            )

        assert first.status_code == 500
        assert retry.status_code == 200
        assert cleanup_calls == [("movie", 902), ("movie", 902)]
        assert imdb_cleanup_calls == [
            ("movie", "tt7654324", "Local Favorite Retry", None, 2024)
        ]
        with TargetSession() as db:
            favorite = db.get(database.Favorite, movie_id)
            assert favorite is not None
            assert favorite.note == "local"
            assert db.query(database.Favorite).count() == 1
    finally:
        engine.dispose()


def test_remove_local_favorite_commits_first_and_retries_external_cleanup(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="123460",
            tmdb_id="903",
            imdb_id="tt7654325",
            title="Local Favorite Delete Retry",
            year=2023,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.flush()
        db.add(database.Favorite(movie_id=movie.id))
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "backup_daily",
        lambda *args, **kwargs: None,
    )

    tmdb_cleanup_calls = []
    def flaky_delete(media_type, provider_id):
        tmdb_cleanup_calls.append((media_type, provider_id))
        if len(tmdb_cleanup_calls) == 1:
            raise OSError("discovery database temporarily unavailable")
        return True

    imdb_cleanup_calls = []
    monkeypatch.setattr(
        favorites_router.provider_response_cache, "delete_favorite", flaky_delete
    )
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite_by_imdb",
        lambda media_type, imdb_id, title, original_title, year: (
            imdb_cleanup_calls.append((media_type, imdb_id, title, original_title, year))
            or False
        ),
    )

    headers = {"X-API-Key": "favorites-test-key"}
    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as client:
            first = client.delete(f"/api/favorites/{movie_id}", headers=headers)
            retry = client.delete(f"/api/favorites/{movie_id}", headers=headers)

        assert first.status_code == 500
        assert retry.status_code == 204
        assert tmdb_cleanup_calls == [("movie", 903), ("movie", 903)]
        # The first attempt stops at the failing TMDB cleanup; the retry
        # then completes both TMDB and corroborated IMDb cleanup.
        assert imdb_cleanup_calls == [
            ("movie", "tt7654325", "Local Favorite Delete Retry", None, 2023),
        ]
        with TargetSession() as db:
            assert db.get(database.Favorite, movie_id) is None
            assert db.get(database.Movie, movie_id) is not None
    finally:
        engine.dispose()


def test_external_favorite_rejects_conflicting_tmdb_and_imdb_local_identities(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        tmdb_match = database.Movie(
            tmdb_id="901",
            title="TMDB Identity Match",
            year=2024,
            type="movie",
            directors="[]",
            actors="[]",
        )
        imdb_match = database.Movie(
            imdb_id="tt7654323",
            title="IMDb Identity Match",
            year=2024,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add_all([tmdb_match, imdb_match])
        db.commit()

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(discovery.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)

    saved_external = []
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "save_favorite",
        lambda *args, **kwargs: saved_external.append((args, kwargs)),
    )

    try:
        with TestClient(main_module.app) as client:
            response = client.put(
                "/api/favorites/external/movie/901",
                headers={"X-API-Key": "favorites-test-key"},
                json={"snapshot": {
                    "title": "Incoming Online Title",
                    "year": 2024,
                    "imdb_id": "tt7654323",
                }},
            )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "TMDB and IMDb identifiers resolve to different local movies"
        )
        assert saved_external == []
        with TargetSession() as db:
            assert db.scalars(select(database.Favorite)).all() == []
    finally:
        engine.dispose()
