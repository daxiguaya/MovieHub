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


def _strip_unapproved_synopsis(value: Any) -> Any:
    """Keep synopsis text out of the persistent response cache."""
    if isinstance(value, dict):
        return {
            key: _strip_unapproved_synopsis(item)
            for key, item in value.items()
            if key != "overview"
        }
    if isinstance(value, list):
        return [_strip_unapproved_synopsis(item) for item in value]
    return value


class TMDBClient:
    async def _cache_get(self, key: str, allow_stale: bool = False):
        """Keep SQLite reads and their locks off the ASGI event loop."""
        try:
            return await asyncio.to_thread(
                provider_response_cache.get, key, allow_stale
            )
        except Exception as exc:
            logger.warning("TMDB response-cache read failed: %s", type(exc).__name__)
            return None

    async def _cache_set(
        self,
        key: str,
        endpoint: str,
        payload: dict[str, Any],
        ttl: int,
    ) -> None:
        """Cache failure must never turn a successful upstream response into 500."""
        try:
            await asyncio.to_thread(
                provider_response_cache.set, key, "tmdb", endpoint, payload, ttl
            )
        except Exception as exc:
            logger.warning("TMDB response-cache write failed: %s", type(exc).__name__)

    def _inflight_done(
        self, key: str, completed: asyncio.Task[dict[str, Any]]
    ) -> None:
        # Consume an exception if every HTTP waiter disconnected before the
        # shared request finished, then remove only this exact task.
        if not completed.cancelled():
            completed.exception()
        asyncio.create_task(self._remove_inflight(key, completed))

    async def _remove_inflight(
        self, key: str, completed: asyncio.Task[dict[str, Any]]
    ) -> None:
        async with _inflight_lock:
            if _inflight.get(key) is completed:
                _inflight.pop(key, None)

    def __init__(self) -> None:
        self.token = settings.tmdb_api_read_token
        self._requests = 0
        self._successes = 0
        self._failures = 0
        self._rate_limited = 0
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0
        # Synopsis is served from bounded process memory only, never persisted.
        self._transient_overviews: dict[str, tuple[float, str]] = {}

    def _remember_transient_overview(self, key: str, overview: str) -> None:
        now = time.monotonic()
        self._transient_overviews = {
            cache_key: value for cache_key, value in self._transient_overviews.items()
            if value[0] > now
        }
        if len(self._transient_overviews) >= 100:
            oldest = min(self._transient_overviews, key=lambda item: self._transient_overviews[item][0])
            self._transient_overviews.pop(oldest, None)
        self._transient_overviews[key] = (now + 6 * 60 * 60, overview[:12000])

    def _get_transient_overview(self, key: str) -> str | None:
        value = self._transient_overviews.get(key)
        if value is None:
            return None
        if value[0] <= time.monotonic():
            self._transient_overviews.pop(key, None)
            return None
        return value[1]

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
        include_overview: bool = False,
    ) -> dict[str, Any]:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        key = provider_response_cache.make_key("tmdb", endpoint, clean_params)
        cached = await self._cache_get(key)
        if cached:
            payload, _ = cached
            if not include_overview:
                return payload
            transient_overview = self._get_transient_overview(key)
            if transient_overview is not None:
                return {**payload, "overview": transient_overview}

        async with _inflight_lock:
            task = _inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._fetch_and_cache(key, endpoint, clean_params, ttl, include_overview)
                )
                _inflight[key] = task
                task.add_done_callback(
                    lambda completed, cache_key=key: self._inflight_done(
                        cache_key, completed
                    )
                )

        try:
            # One disconnected browser request must not cancel the shared
            # upstream request still needed by other callers.
            return await asyncio.shield(task)
        except Exception:
            stale = await self._cache_get(key, allow_stale=True)
            if stale:
                logger.warning("Serving stale TMDB cache after upstream failure: %s", endpoint)
                return stale[0]
            raise

    async def _fetch_and_cache(
        self,
        key: str,
        endpoint: str,
        params: dict[str, Any],
        ttl: int,
        include_overview: bool = False,
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
        if include_overview and isinstance(payload.get("overview"), str) and payload["overview"].strip():
            self._remember_transient_overview(key, payload["overview"])
        cache_payload = _strip_unapproved_synopsis(payload)
        await self._cache_set(key, endpoint, cache_payload, ttl)
        self._successes += 1
        self._record_latency(started)
        return payload


tmdb_client = TMDBClient()
