"""Integration coverage for combined movie-library filters."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.database import Genre, Movie, MovieGenre, MovieRegion, Region


def test_combined_search_filters_apply_all_constraints(tmp_path, monkeypatch):
    db_path = tmp_path / "movie-search.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(engine)
    TargetSession = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    try:
        with TargetSession() as db:
            genre_names = ["剧情", "科幻", "恐怖"]
            genres = {name: Genre(name=name) for name in genre_names}
            region = Region(name="美国")
            db.add_all([*genres.values(), region])
            db.flush()

            movies = [
                Movie(
                    douban_id="search-1",
                    title="星际穿越",
                    original_title="Interstellar",
                    year=2014,
                    rating=8.6,
                    rating_count=10000,
                    imdb_rating=8.6,
                    imdb_rating_count=10000,
                    type="movie",
                    directors="[]",
                    actors="[]",
                ),
                Movie(
                    douban_id="search-2",
                    title="星际恐怖",
                    original_title="Space Horror",
                    year=2015,
                    rating=9.2,
                    rating_count=20000,
                    imdb_rating=9.2,
                    imdb_rating_count=20000,
                    type="movie",
                    directors="[]",
                    actors="[]",
                ),
                Movie(
                    douban_id="search-3",
                    title="星际剧集",
                    original_title="Space Series",
                    year=2016,
                    rating=8.9,
                    rating_count=15000,
                    imdb_rating=8.9,
                    imdb_rating_count=15000,
                    type="tv",
                    directors="[]",
                    actors="[]",
                ),
            ]
            db.add_all(movies)
            db.flush()

            db.add_all([
                MovieGenre(movie_id=movies[0].id, genre_id=genres["剧情"].id),
                MovieGenre(movie_id=movies[0].id, genre_id=genres["科幻"].id),
                MovieGenre(movie_id=movies[1].id, genre_id=genres["剧情"].id),
                MovieGenre(movie_id=movies[1].id, genre_id=genres["科幻"].id),
                MovieGenre(movie_id=movies[1].id, genre_id=genres["恐怖"].id),
                MovieGenre(movie_id=movies[2].id, genre_id=genres["剧情"].id),
                MovieGenre(movie_id=movies[2].id, genre_id=genres["科幻"].id),
                MovieRegion(movie_id=movies[0].id, region_id=region.id),
                MovieRegion(movie_id=movies[1].id, region_id=region.id),
                MovieRegion(movie_id=movies[2].id, region_id=region.id),
            ])
            db.commit()

        with TestClient(main_module.app) as client:
            response = client.get(
                "/api/movies",
                params={
                    "search": "星际",
                    "type": "movie",
                    "min_rating": 8,
                    "min_rating_count": 1000,
                    "min_year": 2000,
                    "max_year": 2020,
                    "genres": "剧情,科幻",
                    "exclude_genres": "恐怖",
                    "regions": "美国",
                    "sort_by": "rating",
                    "sort_order": "desc",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert [item["douban_id"] for item in payload["items"]] == ["search-1"]
        assert payload["items"][0]["genres"] == ["剧情", "科幻"]
        assert payload["items"][0]["regions"] == ["美国"]
        assert payload["next_cursor"] is None
    finally:
        engine.dispose()
