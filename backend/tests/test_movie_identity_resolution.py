import asyncio

from app.routers.movies import _get_linked_tmdb_metadata, tmdb_client


def test_title_year_and_director_match_exposes_transient_tmdb_identity(monkeypatch):
    async def fake_get_json(endpoint, params, ttl, include_overview=False):
        if endpoint == "/search/movie":
            return {"results": [{
                "id": 278, "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
            }]}
        if endpoint == "/movie/278":
            return {
                "id": 278, "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
                "credits": {"crew": [{"name": "Frank Darabont", "job": "Director"}], "cast": []},
                "genres": [], "production_countries": [], "overview": "",
            }
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(tmdb_client, "get_json", fake_get_json)
    result = asyncio.run(_get_linked_tmdb_metadata(
        "movie", None, None, title="肖申克的救赎",
        original_title="The Shawshank Redemption", year=1994,
        directors=["Frank Darabont"],
    ))

    assert result is not None
    assert result["provider_id"] == 278


def test_title_and_year_without_director_does_not_expose_tmdb_identity(monkeypatch):
    async def fake_get_json(endpoint, params, ttl, include_overview=False):
        if endpoint == "/search/movie":
            return {"results": [{
                "id": 278, "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
            }]}
        if endpoint == "/movie/278":
            return {
                "id": 278, "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
                "credits": {"crew": [], "cast": []},
                "genres": [], "production_countries": [], "overview": "",
            }
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(tmdb_client, "get_json", fake_get_json)
    result = asyncio.run(_get_linked_tmdb_metadata(
        "movie", None, None, title="肖申克的救赎",
        original_title="The Shawshank Redemption", year=1994,
        directors=[],
    ))

    assert result is not None
    assert result["provider_id"] is None
