"""Small, bounded TMDB API client with persistent response caching."""
from __future__ import annotations

import asyncio
import logging
import json
import time
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.provider_cache import provider_response_cache

logger = logging.getLogger("moviehub.tmdb")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
SEARCH_TTL = 15 * 60
NEGATIVE_TTL = 2 * 60
DETAIL_TTL = 7 * 24 * 60 * 60
GENRE_TTL = 7 * 24 * 60 * 60
MAX_UPSTREAM_CONCURRENCY = 4
MAX_UPSTREAM_RESPONSE_BYTES = 2 * 1024 * 1024

_semaphore = asyncio.Semaphore(MAX_UPSTREAM_CONCURRENCY)
_inflight_lock = asyncio.Lock()
_inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}


class TMDBClient:
    def __init__(self) -> None:
        self.token = settings.tmdb_api_read_token
        self._requests = 0
        self._successes = 0
        self._failures = 0
        self._rate_limited = 0
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0

    def _record_latency(self, started: float) -> None:
        elapsed = (time.perf_counter() - started) * 1000
        self._total_latency_ms += elapsed
        self._max_latency_ms = max(self._max_latency_ms, elapsed)

    def stats(self) -> dict[str, int | float]:
        return {
            "upstream_requests": self._requests,
            "upstream_successes": self._successes,
            "upstream_failures": self._failures,
            "upstream_rate_limited": self._rate_limited,
            "upstream_avg_latency_ms": round(self._total_latency_ms / self._requests, 2) if self._requests else 0.0,
            "upstream_max_latency_ms": round(self._max_latency_ms, 2),
        }

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise HTTPException(status_code=503, detail="TMDB API is not configured")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "MovieHub/1.0 (+self-hosted discovery)",
        }

    async def get_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        ttl: int = SEARCH_TTL,
    ) -> dict[str, Any]:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        key = provider_response_cache.make_key("tmdb", endpoint, clean_params)
        cached = provider_response_cache.get(key)
        if cached:
            payload, _ = cached
            return payload

        async with _inflight_lock:
            task = _inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._fetch_and_cache(key, endpoint, clean_params, ttl)
                )
                _inflight[key] = task
                owner = True
            else:
                owner = False

        try:
            return await task
        except Exception:
            stale = provider_response_cache.get(key, allow_stale=True)
            if stale:
                logger.warning("Serving stale TMDB cache after upstream failure: %s", endpoint)
                return stale[0]
            raise
        finally:
            if owner:
                async with _inflight_lock:
                    if _inflight.get(key) is task:
                        _inflight.pop(key, None)

    async def _fetch_and_cache(
        self,
        key: str,
        endpoint: str,
        params: dict[str, Any],
        ttl: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        self._requests += 1
        try:
            async with _semaphore:
                async with httpx.AsyncClient(
                    base_url=TMDB_BASE_URL,
                    timeout=httpx.Timeout(8.0, connect=3.0),
                    follow_redirects=False,
                ) as client:
                    async with client.stream(
                        "GET", endpoint, params=params, headers=self._headers()
                    ) as response:
                        if response.status_code == 429:
                            self._rate_limited += 1
                            raise HTTPException(
                                status_code=503,
                                detail="TMDB rate limit reached; please retry later",
                                headers={"Retry-After": response.headers.get("Retry-After", "30")},
                            )
                        if response.status_code >= 500:
                            raise HTTPException(status_code=502, detail="TMDB is temporarily unavailable")
                        if response.status_code >= 400:
                            raise HTTPException(status_code=502, detail="TMDB rejected the discovery request")
                        chunks: list[bytes] = []
                        received = 0
                        async for chunk in response.aiter_bytes():
                            received += len(chunk)
                            if received > MAX_UPSTREAM_RESPONSE_BYTES:
                                raise HTTPException(status_code=502, detail="TMDB response exceeded the size limit")
                            chunks.append(chunk)
                        try:
                            payload = json.loads(b"".join(chunks))
                        except json.JSONDecodeError as exc:
                            raise HTTPException(status_code=502, detail="TMDB returned invalid JSON") from exc
        except HTTPException:
            self._failures += 1
            self._record_latency(started)
            raise
        except httpx.TimeoutException as exc:
            self._failures += 1
            self._record_latency(started)
            raise HTTPException(status_code=504, detail="TMDB request timed out") from exc
        except httpx.HTTPError as exc:
            self._failures += 1
            self._record_latency(started)
            raise HTTPException(status_code=502, detail="TMDB request failed") from exc

        if isinstance(payload, list):
            payload = {"items": payload}
        if not isinstance(payload, dict):
            self._failures += 1
            self._record_latency(started)
            raise HTTPException(status_code=502, detail="TMDB returned an invalid response")
        if isinstance(payload.get("results"), list) and not payload["results"]:
            ttl = NEGATIVE_TTL
        provider_response_cache.set(key, "tmdb", endpoint, payload, ttl)
        self._successes += 1
        self._record_latency(started)
        return payload


tmdb_client = TMDBClient()
