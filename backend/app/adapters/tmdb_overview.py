"""Read-only TMDB overview lookup with conservative identity matching.

This module deliberately does not write movie metadata or synopsis text to disk.
It is used by the audit/dry-run CLI; accepted content import is a separate,
license-gated operation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
import unicodedata
from typing import Any, Callable

import httpx


TMDB_API_BASE = "https://api.themoviedb.org/3"
USER_AGENT = "MovieHub/0.1 (private self-hosted catalog; contact: repository owner)"


def normalize_title(value: str | None) -> str:
    """Normalize title punctuation/spacing while preserving letters and digits."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


@dataclass(frozen=True)
class OverviewLookup:
    status: str
    media_type: str
    tmdb_id: int | None = None
    match_method: str | None = None
    matched_title: str | None = None
    release_date: str | None = None
    language: str | None = None
    overview_length: int = 0
    overview_sha256: str | None = None
    source_url: str | None = None
    candidate_count: int = 0


class TMDBOverviewClient:
    """Small sequential TMDB client for an explicitly requested dry run."""

    def __init__(
        self,
        access_token: str,
        *,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 0.3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise ValueError("TMDB API read token is required")
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        self._client = client or httpx.Client(
            base_url=TMDB_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._last_request_at = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TMDBOverviewClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)

        response = self._client.get(path, params=params)
        self._last_request_at = time.monotonic()
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "2")
            try:
                delay = min(max(float(retry_after), 1.0), 30.0)
            except ValueError:
                delay = 2.0
            self._sleep(delay)
            response = self._client.get(path, params=params)
            self._last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TMDB response must be a JSON object")
        return payload

    @staticmethod
    def _media_type(value: str) -> str:
        if value not in {"movie", "tv"}:
            raise ValueError("media_type must be 'movie' or 'tv'")
        return value

    @staticmethod
    def _year_of(candidate: dict[str, Any], media_type: str) -> int | None:
        key = "release_date" if media_type == "movie" else "first_air_date"
        value = candidate.get(key)
        if not isinstance(value, str) or len(value) < 4 or not value[:4].isdigit():
            return None
        return int(value[:4])

    @staticmethod
    def _title_names(candidate: dict[str, Any], media_type: str) -> set[str]:
        keys = ("title", "original_title") if media_type == "movie" else ("name", "original_name")
        return {
            normalized
            for key in keys
            if (normalized := normalize_title(candidate.get(key)))
        }

    @classmethod
    def _matches_title_and_year(
        cls,
        item: Any,
        candidate: dict[str, Any],
        media_type: str,
    ) -> bool:
        expected_year = getattr(item, "year", None)
        candidate_year = cls._year_of(candidate, media_type)
        if expected_year is None or candidate_year != expected_year:
            return False
        item_names = {
            normalize_title(getattr(item, "title", None)),
            normalize_title(getattr(item, "original_title", None)),
        } - {""}
        if not item_names:
            return False
        return bool(item_names & cls._title_names(candidate, media_type))

    def _search_by_title_and_directors(
        self,
        item: Any,
        media_type: str,
        language: str,
    ) -> tuple[dict[str, Any] | None, str, int]:
        """Resolve yearless source rows only when exact title and director agree.

        Annual charts may omit release years. In that case a title-only result
        is never accepted: every exact-title candidate is cross-checked against
        TMDB credits and the source's director names. Multiple matches remain
        ambiguous and missing director evidence remains insufficient identity.
        """
        query_values = []
        for value in (
            getattr(item, "original_title", None),
            getattr(item, "title", None),
        ):
            value = (value or "").strip()
            if value and value not in query_values:
                query_values.append(value)

        source_directors = {
            normalize_title(name)
            for name in (getattr(item, "directors", None) or [])
            if normalize_title(name)
        }
        if not query_values or not source_directors:
            return None, "insufficient_identity", 0

        candidates_by_id: dict[int, dict[str, Any]] = {}
        for query in query_values:
            payload = self._get(
                f"/search/{media_type}",
                {
                    "query": query,
                    "include_adult": "false",
                    # The annual source title is captured in Simplified Chinese;
                    # keep identity resolution locale-stable for both audit locales.
                    "language": "zh-CN",
                    "page": 1,
                },
            )
            results = payload.get("results", [])
            if not isinstance(results, list):
                continue
            for candidate in results:
                if not isinstance(candidate, dict) or candidate.get("id") is None:
                    continue
                if normalize_title(getattr(item, "title", None)) in self._title_names(candidate, media_type) or normalize_title(getattr(item, "original_title", None)) in self._title_names(candidate, media_type):
                    candidates_by_id[int(candidate["id"])] = candidate

        if not candidates_by_id:
            return None, "no_exact_match", 0

        verified: list[dict[str, Any]] = []
        for candidate_id, candidate in candidates_by_id.items():
            credits = self._get(
                f"/{media_type}/{candidate_id}/credits",
                {},
            )
            crew = credits.get("crew", [])
            if not isinstance(crew, list):
                continue
            tmdb_directors = {
                normalize_title(person.get("name"))
                for person in crew
                if isinstance(person, dict)
                and (
                    person.get("job") == "Director"
                    or (media_type == "tv" and person.get("department") == "Directing")
                )
                and normalize_title(person.get("name"))
            }
            if source_directors & tmdb_directors:
                verified.append(candidate)

        if len(verified) == 1:
            return verified[0], "exact_title_director", 1
        if len(verified) > 1:
            return None, "ambiguous", len(verified)
        return None, "no_exact_match", len(candidates_by_id)

    def _find_by_imdb_id(
        self,
        item: Any,
        media_type: str,
    ) -> tuple[dict[str, Any] | None, str, int]:
        imdb_id = (getattr(item, "imdb_id", None) or "").strip()
        if not imdb_id:
            return None, "no_external_id", 0
        if not re.fullmatch(r"tt[0-9]{7,12}", imdb_id):
            return None, "invalid_external_id", 0
        payload = self._get(
            f"/find/{imdb_id}",
            {"external_source": "imdb_id"},
        )
        key = "movie_results" if media_type == "movie" else "tv_results"
        candidates = payload.get(key, [])
        if not isinstance(candidates, list):
            candidates = []
        valid = [
            candidate for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("id") is not None
            and self._matches_title_and_year(item, candidate, media_type)
        ]
        if len(valid) == 1:
            return valid[0], "imdb_id", len(valid)
        if len(valid) > 1:
            return None, "ambiguous", len(valid)
        return None, "id_mismatch_or_not_found", len(candidates)

    def _search_by_title(
        self,
        item: Any,
        media_type: str,
        language: str,
    ) -> tuple[dict[str, Any] | None, str, int]:
        query_values = []
        for value in (
            getattr(item, "original_title", None),
            getattr(item, "title", None),
        ):
            value = (value or "").strip()
            if value and value not in query_values:
                query_values.append(value)
        if not query_values or getattr(item, "year", None) is None:
            return None, "insufficient_identity", 0

        key = "primary_release_year" if media_type == "movie" else "first_air_date_year"
        candidates_by_id: dict[int, dict[str, Any]] = {}
        for query in query_values:
            payload = self._get(
                f"/search/{media_type}",
                {
                    "query": query,
                    key: int(item.year),
                    "include_adult": "false",
                    "language": language,
                    "page": 1,
                },
            )
            results = payload.get("results", [])
            if not isinstance(results, list):
                continue
            for candidate in results:
                if not isinstance(candidate, dict) or candidate.get("id") is None:
                    continue
                if self._matches_title_and_year(item, candidate, media_type):
                    candidates_by_id[int(candidate["id"])] = candidate

        candidates = list(candidates_by_id.values())
        if len(candidates) == 1:
            return candidates[0], "exact_title_year", 1
        if len(candidates) > 1:
            return None, "ambiguous", len(candidates)
        return None, "no_exact_match", 0

    def lookup(self, item: Any, language: str = "zh-CN") -> OverviewLookup:
        media_type = self._media_type(getattr(item, "type", "movie"))
        known_tmdb_id = (getattr(item, "tmdb_id", None) or "").strip()
        details: dict[str, Any] | None = None

        if known_tmdb_id:
            if not known_tmdb_id.isdigit() or int(known_tmdb_id) <= 0:
                return OverviewLookup(
                    status="invalid_tmdb_id",
                    media_type=media_type,
                )
            details = self._get(
                f"/{media_type}/{int(known_tmdb_id)}",
                {"language": language},
            )
            if not self._matches_title_and_year(item, details, media_type):
                return OverviewLookup(
                    status="tmdb_id_identity_mismatch",
                    media_type=media_type,
                    tmdb_id=int(known_tmdb_id),
                    match_method="tmdb_id",
                    candidate_count=1,
                )
            method = "tmdb_id"
            candidate_count = 1
        else:
            candidate, method, candidate_count = self._find_by_imdb_id(item, media_type)
            if candidate is None and method == "no_external_id":
                if getattr(item, "year", None) is None:
                    candidate, method, candidate_count = self._search_by_title_and_directors(
                        item, media_type, language
                    )
                else:
                    candidate, method, candidate_count = self._search_by_title(item, media_type, language)
            elif candidate is None:
                return OverviewLookup(
                    status=method,
                    media_type=media_type,
                    candidate_count=candidate_count,
                )

            if candidate is None:
                return OverviewLookup(
                    status=method,
                    media_type=media_type,
                    candidate_count=candidate_count,
                )

            tmdb_id = int(candidate["id"])
            details = self._get(
                f"/{media_type}/{tmdb_id}",
                {"language": language},
            )

        tmdb_id = int(details["id"])
        overview = details.get("overview")
        if not isinstance(overview, str) or not overview.strip():
            return OverviewLookup(
                status="no_overview",
                media_type=media_type,
                tmdb_id=tmdb_id,
                match_method=method,
                matched_title=str(
                    details.get("title") or details.get("name") or ""
                ) or None,
                release_date=(
                    details.get("release_date") or details.get("first_air_date")
                ),
                language=language,
                source_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
                candidate_count=candidate_count,
            )

        import hashlib

        clean_overview = overview.strip()
        return OverviewLookup(
            status="overview_available",
            media_type=media_type,
            tmdb_id=tmdb_id,
            match_method=method,
            matched_title=str(
                details.get("title") or details.get("name") or ""
            ) or None,
            release_date=(
                details.get("release_date") or details.get("first_air_date")
            ),
            language=language,
            overview_length=len(clean_overview),
            overview_sha256=hashlib.sha256(
                clean_overview.encode("utf-8")
            ).hexdigest(),
            source_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
            candidate_count=candidate_count,
        )
