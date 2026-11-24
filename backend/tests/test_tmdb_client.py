"""Tests for TMDB request safety and concurrency controls."""

import asyncio

import httpx
import pytest

from app.services.tmdb_client import TMDBClient, TMDBError


def test_missing_token_fails_closed():
    async def scenario():
        client = TMDBClient(token="")
        try:
            with pytest.raises(TMDBError) as error:
                await client.get("/search/movie", {"query": "Alien"})
            assert error.value.status_code == 503
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_authorization_and_query_normalization():
    async def scenario():
        seen = {}
        async def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("Authorization")
            seen["query"] = request.url.params.get("query")
            seen["page"] = request.url.params.get("page")
            return httpx.Response(200, json={"page": 1, "results": []})
        client = TMDBClient(token="test-secret", transport=httpx.MockTransport(handler))
        try:
            result = await client.get("/search/movie", {"query": "  Alien  ", "page": "1", "unused": None})
            assert result == {"page": 1, "results": []}
            assert seen == {"authorization": "Bearer test-secret", "query": "Alien", "page": "1"}
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_identical_concurrent_requests_are_single_flight():
    async def scenario():
        calls = 0
        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.03)
            return httpx.Response(200, json={"results": [{"id": 1}]})
        client = TMDBClient(token="test-secret", transport=httpx.MockTransport(handler))
        try:
            first, second = await asyncio.gather(
                client.get("/search/movie", {"query": "Alien", "page": 1}),
                client.get("/search/movie", {"page": 1, "query": "Alien"}),
            )
            assert first == second
            assert calls == 1
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_429_is_not_retried_and_retry_after_is_exposed():
    async def scenario():
        calls = 0
        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"status_message": "limited"})
        client = TMDBClient(token="test-secret", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(TMDBError) as error:
                await client.get("/search/movie", {"query": "Alien"})
            assert error.value.status_code == 429
            assert error.value.retry_after == 7
            assert calls == 1
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_page_limit_is_validated_before_request():
    assert TMDBClient._normalize_params({"page": 500})["page"] == 500
    with pytest.raises(ValueError):
        TMDBClient._normalize_params({"page": 501})