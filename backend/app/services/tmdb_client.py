"""Bounded, authenticated client for the TMDB v3 API."""

from __future__ import annotations

import asyncio
import email.utils
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("moviehub.tmdb")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
MAX_PAGE = 500
MAX_RETRIES = 1
MAX_RETRY_AFTER_SECONDS = 30


class TMDBError(RuntimeError):
    """Safe upstream error; never includes request headers or credentials."""

    def __init__(self, message: str, status_code: int = 502, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TMDBClient:
    """One shared HTTP client with a strict concurrency cap and single-flight."""

    def __init__(
        self,
        token: str | None = None,
        max_concurrency: int | None = None,
        timeout_seconds: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = (token if token is not None else settings.tmdb_api_read_token).strip()
        self._semaphore = asyncio.Semaphore(max(1, min(int(max_concurrency or settings.tmdb_max_concurrency), 4)))
        self._singleflight_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._client = httpx.AsyncClient(
            base_url=TMDB_BASE_URL,
            headers={
                "Accept": "application/json",
                **({"Authorization": f"Bearer {self._token}"} if self._token else {}),
            },
            timeout=httpx.Timeout(timeout_seconds, connect=min(3.0, timeout_seconds)),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, min(float(value), MAX_RETRY_AFTER_SECONDS))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, min(parsed.timestamp() - time.time(), MAX_RETRY_AFTER_SECONDS))
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _normalize_params(params: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized[key] = "true" if value else "false"
            elif isinstance(value, (list, tuple, set)):
                normalized[key] = ",".join(sorted(str(item).strip() for item in value if str(item).strip()))
            elif isinstance(value, str):
                normalized[key] = value.strip()
            else:
                normalized[key] = value
        if "page" in normalized:
            try:
                page = int(normalized["page"])
            except (TypeError, ValueError) as exc:
                raise ValueError("TMDB page must be an integer") from exc
            if page < 1 or page > MAX_PAGE:
                raise ValueError(f"TMDB page must be between 1 and {MAX_PAGE}")
            normalized["page"] = page
        return normalized

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET one TMDB endpoint; identical concurrent requests share one task."""
        if not self.configured:
            raise TMDBError("TMDB is not configured on the server", status_code=503)
        if not path.startswith("/") or ".." in path.split("/") or "://" in path:
            raise ValueError("TMDB endpoint must be a safe relative API path")

        normalized = self._normalize_params(params)
        key = path + "?" + "&".join(f"{k}={normalized[k]}" for k in sorted(normalized))
        async with self._singleflight_lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._request(path, normalized))
                self._inflight[key] = task

        try:
            # Shield prevents one disconnected browser request from cancelling
            # a shared upstream request needed by other callers.
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._singleflight_lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

    async def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = await self._client.get(path, params=params)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(0.25 * (attempt + 1))
                        continue
                    logger.warning("TMDB network request failed: %s", type(exc).__name__)
                    raise TMDBError("TMDB is temporarily unreachable", status_code=502) from exc

                if response.status_code == 429:
                    retry_after = self._retry_after(response.headers.get("Retry-After"))
                    raise TMDBError("TMDB rate limit reached", status_code=429, retry_after=retry_after)
                if response.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    safe_status = 404 if response.status_code == 404 else 502
                    raise TMDBError("TMDB rejected the request", status_code=safe_status)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise TMDBError("TMDB returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise TMDBError("TMDB returned an unexpected response")
                return payload

        raise TMDBError("TMDB request failed")


tmdb_client = TMDBClient()


__all__ = ["TMDBClient", "TMDBError", "tmdb_client"]