"""Demand-driven TMDB enrichment must verify a local chart movie's identity."""

import asyncio

from app.routers import movies


def test_local_chart_movie_resolves_one_exact_tmdb_title_year_and_director(monkeypatch):
    calls = []

    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        calls.append((endpoint, params, include_overview))
        if endpoint == "/search/movie":
            assert params["primary_release_year"] == 1994
            return {
                "results": [{
                    "id": 278,
                    "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]
            }
        if endpoint == "/movie/278":
            assert include_overview is True
            return {
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
                "overview": "一段经过身份核验的临时简介。",
                "vote_average": 9.3,
                "vote_count": 2500000,
                "credits": {
                    "crew": [{
                        "job": "Director",
                        "name": "弗兰克·德拉邦特",
                    }],
                    "cast": [],
                },
                "genres": [{"name": "剧情"}],
                "production_countries": [{"name": "美国"}],
            }
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(movies.tmdb_client, "get_json", fake_get_json)

    result = asyncio.run(movies._get_linked_tmdb_metadata(
        "movie",
        None,
        None,
        title="肖申克的救赎",
        original_title="The Shawshank Redemption",
        year=1994,
        directors=["弗兰克·德拉邦特"],
    ))

    assert result is not None
    assert result["overview"] == "一段经过身份核验的临时简介。"
    assert result["rating"] == 9.3
    assert result["rating_count"] == 2500000
    assert [call[0] for call in calls] == ["/search/movie", "/search/movie", "/movie/278"]


def test_local_chart_movie_does_not_accept_ambiguous_tmdb_candidates(monkeypatch):
    calls = []

    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        calls.append(endpoint)
        return {
            "results": [
                {"id": 278, "title": "同名电影", "original_title": "Same Film", "release_date": "2000-01-01"},
                {"id": 999, "title": "同名电影", "original_title": "Same Film", "release_date": "2000-10-01"},
            ]
        }

    monkeypatch.setattr(movies.tmdb_client, "get_json", fake_get_json)

    result = asyncio.run(movies._get_linked_tmdb_metadata(
        "movie", None, None, title="同名电影", original_title="Same Film",
        year=2000, directors=["导演甲"],
    ))

    assert result is None
    assert calls == ["/search/movie", "/search/movie", "/movie/278", "/movie/999"]


def test_local_chart_movie_rejects_tmdb_director_mismatch(monkeypatch):
    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        if endpoint == "/search/movie":
            return {"results": [{
                "id": 278, "title": "同名电影", "original_title": "Same Film",
                "release_date": "2000-01-01",
            }]}
        if endpoint == "/movie/278":
            return {
                "id": 278, "title": "同名电影", "original_title": "Same Film",
                "release_date": "2000-01-01", "overview": "不应展示",
                "credits": {"crew": [{"job": "Director", "name": "另一位导演"}], "cast": []},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(movies.tmdb_client, "get_json", fake_get_json)

    result = asyncio.run(movies._get_linked_tmdb_metadata(
        "movie", None, None, title="同名电影", original_title="Same Film",
        year=2000, directors=["导演甲"],
    ))

    assert result is None
