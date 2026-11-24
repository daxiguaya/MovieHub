from types import SimpleNamespace

import httpx
import pytest

from app.adapters.tmdb_overview import TMDB_API_BASE, TMDBOverviewClient


def _client(handler):
    return httpx.Client(
        base_url=TMDB_API_BASE,
        transport=httpx.MockTransport(handler),
    )


def _item(**overrides):
    values = {
        "title": "肖申克的救赎",
        "original_title": "The Shawshank Redemption",
        "year": 1994,
        "type": "movie",
        "imdb_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_tmdb_lookup_accepts_one_exact_title_year_and_returns_hash_only():
    def handler(request):
        if request.url.path == "/3/search/movie":
            assert request.url.params["language"] == "zh-CN"
            return httpx.Response(200, json={
                "results": [{
                    "id": 278,
                    "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]
            })
        if request.url.path == "/3/movie/278":
            assert request.url.params["language"] == "zh-CN"
            return httpx.Response(200, json={
                "id": 278,
                "title": "肖申克的救赎",
                "release_date": "1994-09-23",
                "overview": "一段真实的剧情简介文本",
            })
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient(
            "test-token",
            client=transport,
            min_interval_seconds=0,
        ) as client:
            result = client.lookup(_item())

    assert result.status == "overview_available"
    assert result.tmdb_id == 278
    assert result.match_method == "exact_title_year"
    assert result.language == "zh-CN"
    assert result.overview_length > 0
    assert len(result.overview_sha256) == 64
    assert "一段真实的剧情简介文本" not in repr(result)


def test_tmdb_lookup_rejects_ambiguous_exact_candidates():
    def handler(request):
        return httpx.Response(200, json={
            "results": [
                {
                    "id": 278,
                    "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                },
                {
                    "id": 999,
                    "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-10-01",
                },
            ]
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item())

    assert result.status == "ambiguous"
    assert result.tmdb_id is None
    assert result.candidate_count == 2


def test_tmdb_lookup_rejects_year_mismatch_even_when_title_matches():
    def handler(request):
        return httpx.Response(200, json={
            "results": [{
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "release_date": "1995-01-01",
            }]
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item())

    assert result.status == "no_exact_match"


def test_tmdb_lookup_uses_imdb_external_id_but_cross_checks_identity():
    def handler(request):
        if request.url.path == "/3/find/tt0111161":
            assert request.url.params["external_source"] == "imdb_id"
            return httpx.Response(200, json={
                "movie_results": [{
                    "id": 278,
                    "title": "The Shawshank Redemption",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]
            })
        if request.url.path == "/3/movie/278":
            return httpx.Response(200, json={
                "id": 278,
                "title": "The Shawshank Redemption",
                "release_date": "1994-09-23",
                "overview": "A genuine plot description.",
            })
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(imdb_id="tt0111161"))

    assert result.status == "overview_available"
    assert result.match_method == "imdb_id"
    assert result.tmdb_id == 278


def test_tmdb_lookup_rejects_imdb_identity_mismatch_without_search_fallback():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={
            "movie_results": [{
                "id": 999,
                "title": "Different Movie",
                "original_title": "Different Movie",
                "release_date": "1994-01-01",
            }]
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(imdb_id="tt0111161"))

    assert result.status == "id_mismatch_or_not_found"
    assert requests == ["/3/find/tt0111161"]


def test_tmdb_lookup_keeps_empty_localized_overview_empty():
    def handler(request):
        if request.url.path == "/3/search/movie":
            return httpx.Response(200, json={
                "results": [{
                    "id": 278,
                    "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]
            })
        return httpx.Response(200, json={
            "id": 278,
            "title": "肖申克的救赎",
            "release_date": "1994-09-23",
            "overview": "   ",
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item())

    assert result.status == "no_overview"
    assert result.overview_length == 0
    assert result.overview_sha256 is None


def test_tmdb_client_requires_token_and_rejects_invalid_media_type():
    with pytest.raises(ValueError, match="read token"):
        TMDBOverviewClient(" ")

    with _client(lambda request: httpx.Response(200, json={})) as transport:
        with TMDBOverviewClient("test-token", client=transport) as client:
            with pytest.raises(ValueError, match="media_type"):
                client.lookup(_item(type="episode"))

def test_tmdb_lookup_uses_requested_locale_for_search_and_details():
    def handler(request):
        assert request.url.params["language"] == "zh-TW"
        if request.url.path == "/3/search/movie":
            return httpx.Response(200, json={
                "results": [{
                    "id": 278,
                    "title": "刺激1995",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]
            })
        if request.url.path == "/3/movie/278":
            return httpx.Response(200, json={
                "id": 278,
                "title": "刺激1995",
                "release_date": "1994-09-23",
                "overview": "繁體中文劇情簡介。",
            })
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(), language="zh-TW")

    assert result.status == "overview_available"
    assert result.language == "zh-TW"

def test_tmdb_lookup_prioritizes_existing_tmdb_id_and_cross_checks_identity():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        assert request.url.params["language"] == "zh-CN"
        return httpx.Response(200, json={
            "id": 278,
            "title": "肖申克的救赎",
            "original_title": "The Shawshank Redemption",
            "release_date": "1994-09-23",
            "overview": "真实剧情简介。",
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(tmdb_id="278"))

    assert result.status == "overview_available"
    assert result.match_method == "tmdb_id"
    assert result.tmdb_id == 278
    assert requests == ["/3/movie/278"]


def test_tmdb_lookup_rejects_existing_tmdb_id_when_title_or_year_conflicts():
    def handler(request):
        return httpx.Response(200, json={
            "id": 278,
            "title": "Different Movie",
            "original_title": "Different Movie",
            "release_date": "1994-09-23",
            "overview": "Do not accept this overview.",
        })

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(tmdb_id="278"))

    assert result.status == "tmdb_id_identity_mismatch"
    assert result.overview_sha256 is None


def test_yearless_annual_item_requires_exact_title_and_matching_director():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/3/search/movie":
            return httpx.Response(200, json={"results": [{
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
            }]})
        if request.url.path == "/3/movie/278/credits":
            return httpx.Response(200, json={"crew": [{
                "job": "Director",
                "name": "Frank Darabont",
            }]})
        if request.url.path == "/3/movie/278":
            return httpx.Response(200, json={
                "id": 278,
                "title": "肖申克的救赎",
                "release_date": "1994-09-23",
                "overview": "一段真实的剧情简介。",
            })
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(year=None, directors=["Frank Darabont"]))

    assert result.status == "overview_available"
    assert result.match_method == "exact_title_director"
    assert result.tmdb_id == 278
    assert requests.count("/3/movie/278/credits") == 1


def test_yearless_annual_item_rejects_director_mismatch():
    def handler(request):
        if request.url.path == "/3/search/movie":
            return httpx.Response(200, json={"results": [{
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
            }]})
        if request.url.path == "/3/movie/278/credits":
            return httpx.Response(200, json={"crew": [{
                "job": "Director",
                "name": "Someone Else",
            }]})
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(year=None, directors=["Frank Darabont"]))

    assert result.status == "no_exact_match"
    assert result.tmdb_id is None


def test_yearless_annual_item_without_director_is_insufficient_identity():
    def handler(request):
        raise AssertionError(f"No provider request expected: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(_item(year=None, directors=[]))

    assert result.status == "insufficient_identity"


def test_yearless_annual_identity_uses_source_locale_but_fetches_requested_locale():
    def handler(request):
        if request.url.path == "/3/search/movie":
            assert request.url.params["language"] == "zh-CN"
            return httpx.Response(200, json={"results": [{
                "id": 278,
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
            }]})
        if request.url.path == "/3/movie/278/credits":
            return httpx.Response(200, json={"crew": [{
                "job": "Director", "name": "Frank Darabont",
            }]})
        if request.url.path == "/3/movie/278":
            assert request.url.params["language"] == "zh-TW"
            return httpx.Response(200, json={
                "id": 278,
                "title": "刺激1995",
                "release_date": "1994-09-23",
                "overview": "繁體中文劇情簡介。",
            })
        raise AssertionError(f"Unexpected request: {request.url}")

    with _client(handler) as transport:
        with TMDBOverviewClient("test-token", client=transport, min_interval_seconds=0) as client:
            result = client.lookup(
                _item(year=None, directors=["Frank Darabont"]),
                language="zh-TW",
            )

    assert result.status == "overview_available"
    assert result.match_method == "exact_title_director"
    assert result.language == "zh-TW"
