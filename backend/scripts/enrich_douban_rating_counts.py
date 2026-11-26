"""Fill missing Douban rating counts for annual charts via the public mobile subject API.

Read-only dry-run is the default. The collector checks m.douban.com/robots.txt,
uses only stored Douban subject IDs, requests one detail at a time, and stops
immediately on redirects, access denial, rate limits, or unexpected responses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select

from app.database import (
    Chart, ChartItem, ChartSnapshot, Movie, MovieMetadataProvenance,
    SessionLocal,
)
from scripts.db_backup import create_backup

ANNUAL_SLUGS = (
    "annual-2025-chinese-movies",
    "annual-2025-international-movies",
    "annual-2025-hidden-gems",
    "annual-2025-chinese-tv",
)
DOUBAN_MOBILE = "https://m.douban.com"
ROBOTS_URL = f"{DOUBAN_MOBILE}/robots.txt"
USER_AGENT = "MovieHubDoubanMetadata/1.0 (self-hosted personal use)"
REQUEST_DELAY_SECONDS = 2.5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class DoubanMetadataError(RuntimeError):
    """A safe, actionable error while retrieving public Douban metadata."""


def _normalise(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def _sha256(value: int) -> str:
    return hashlib.sha256(str(value).encode("ascii")).hexdigest()


def _check_status(response: httpx.Response, url: str) -> dict[str, Any]:
    status = response.status_code
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        raise DoubanMetadataError(
            "Douban returned HTTP 429; stopped without retry"
            + (f" (Retry-After: {retry_after})" if retry_after else "")
        )
    if status in (401, 403):
        raise DoubanMetadataError(
            f"Douban denied access to {url} (HTTP {status}); no bypass attempted"
        )
    if 300 <= status < 400:
        raise DoubanMetadataError(f"Unexpected redirect from {url}; redirects are disabled")
    if status != 200:
        raise DoubanMetadataError(f"Unexpected HTTP {status} from {url}")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise DoubanMetadataError("Douban response exceeded the 2 MiB safety limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise DoubanMetadataError("Douban returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DoubanMetadataError("Douban returned a non-object JSON response")
    return payload


def _check_robots(client: httpx.Client, media_types: set[str]) -> None:
    response = client.get(ROBOTS_URL)
    if response.status_code != 200:
        raise DoubanMetadataError(
            f"Could not verify m.douban.com/robots.txt (HTTP {response.status_code}); "
            "stopping without requests"
        )
    if len(response.content) > 256 * 1024:
        raise DoubanMetadataError("Douban robots.txt exceeded the safety limit")
    parser = RobotFileParser()
    parser.set_url(ROBOTS_URL)
    parser.parse(response.text.splitlines())
    for media_type in sorted(media_types):
        endpoint = f"{DOUBAN_MOBILE}/rexxar/api/v2/{media_type}/123456"
        if not parser.can_fetch(USER_AGENT, endpoint):
            raise DoubanMetadataError(
                f"m.douban.com robots.txt disallows the {media_type} detail endpoint"
            )


def _extract_count(movie: Movie, payload: dict[str, Any]) -> int | None:
    """Accept count only when the stored Douban ID, media type and title agree."""
    if str(payload.get("id") or "") != str(movie.douban_id):
        raise ValueError("Douban subject ID does not match stored ID")

    title_keys = ("title", "name")
    provider_titles = {
        _normalise(payload.get(key)) for key in title_keys if payload.get(key)
    }
    provider_titles.discard("")
    stored_titles = {
        _normalise(movie.title),
        _normalise(movie.original_title),
    }
    stored_titles.discard("")
    if not provider_titles.intersection(stored_titles):
        raise ValueError(
            f"Douban title identity mismatch: stored={movie.title!r}, "
            f"provider={sorted(provider_titles)!r}"
        )

    rating = payload.get("rating")
    if not isinstance(rating, dict):
        return None
    count = rating.get("count")
    if type(count) is not int or count < 0:
        return None
    return count


def _load_targets() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Movie)
            .join(ChartItem, ChartItem.movie_id == Movie.id)
            .join(ChartSnapshot, ChartSnapshot.id == ChartItem.snapshot_id)
            .join(Chart, Chart.list_id == ChartSnapshot.list_id)
            .where(Chart.slug.in_(ANNUAL_SLUGS))
            .distinct()
            .order_by(Movie.id)
        ).scalars().all()
        return [
            {
                "id": movie.id,
                "douban_id": movie.douban_id,
                "type": movie.type,
                "title": movie.title,
                "original_title": movie.original_title,
                "rating_count": movie.rating_count,
            }
            for movie in rows
        ]


def _collect(targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter, list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    counts: Counter = Counter()
    errors: list[dict[str, Any]] = []
    candidates = [row for row in targets if row["douban_id"] and str(row["douban_id"]).isdigit()]
    counts["missing_douban_id"] = len(targets) - len(candidates)
    media_types = {row["type"] for row in candidates}
    if not candidates:
        return accepted, counts, errors

    with httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    ) as client:
        _check_robots(client, media_types)
        for index, row in enumerate(candidates):
            if index:
                time.sleep(REQUEST_DELAY_SECONDS)
            media_type = row["type"]
            if media_type not in {"movie", "tv"}:
                counts["unsupported_type"] += 1
                errors.append({"id": row["id"], "reason": f"unsupported media type: {media_type}"})
                continue
            subject_id = str(row["douban_id"])
            url = f"{DOUBAN_MOBILE}/rexxar/api/v2/{media_type}/{subject_id}"
            try:
                response = client.get(
                    url,
                    headers={"Referer": f"{DOUBAN_MOBILE}/{media_type}/subject/{subject_id}/"},
                )
                payload = _check_status(response, url)
                count = _extract_count(_target_movie(row), payload)
                if count is None:
                    counts["rating_count_unavailable"] += 1
                    continue
                counts["identity_verified"] += 1
                if row["rating_count"] is not None:
                    counts["already_populated"] += 1
                    continue
                accepted.append({"target": row, "rating_count": count})
            except (httpx.HTTPError, ValueError, DoubanMetadataError) as exc:
                if isinstance(exc, DoubanMetadataError) and (
                    "HTTP 429" in str(exc) or "HTTP 403" in str(exc)
                    or "HTTP 401" in str(exc) or "redirect" in str(exc)
                    or "robots.txt" in str(exc)
                ):
                    raise
                errors.append({"id": row["id"], "douban_id": subject_id, "reason": str(exc)[:240]})
                counts["identity_or_request_rejected"] += 1
    return accepted, counts, errors


def _target_movie(row: dict[str, Any]):
    from types import SimpleNamespace
    return SimpleNamespace(**row)


def _apply(records: list[dict[str, Any]], apply: bool) -> int:
    changed = 0
    observed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        for record in records:
            target = record["target"]
            movie = db.get(Movie, target["id"])
            if movie is None or movie.rating_count is not None:
                continue
            count = record["rating_count"]
            movie.rating_count = count
            db.add(MovieMetadataProvenance(
                movie_id=movie.id,
                field_name="rating_count",
                source="douban",
                source_url=f"https://movie.douban.com/subject/{movie.douban_id}/",
                observed_at=observed_at,
                value_sha256=_sha256(count),
            ))
            changed += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Identity-checked annual-chart Douban rating-count enrichment"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true", help="Write verified missing Douban counts")
    args = parser.parse_args()
    apply = bool(args.apply)

    targets = _load_targets()
    if not targets:
        print(json.dumps({"success": False, "error": "No annual chart records found"}, ensure_ascii=False))
        return 2

    try:
        accepted, counts, errors = _collect(targets)
        planned = sum(
            1 for row in accepted
            if row["target"]["rating_count"] is None
        )
        backup = create_backup() if apply and planned else None
        changed = _apply(accepted, apply)
    except Exception as exc:
        print(json.dumps({
            "success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "database_written": False,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    report = {
        "success": True,
        "mode": "apply" if apply else "dry-run",
        "target_records": len(targets),
        "with_douban_id": sum(1 for row in targets if row["douban_id"] and str(row["douban_id"]).isdigit()),
        "without_douban_id": counts["missing_douban_id"],
        "identity_verified": counts["identity_verified"],
        "already_populated": counts["already_populated"],
        "rating_count_unavailable": counts["rating_count_unavailable"],
        "identity_or_request_rejected": counts["identity_or_request_rejected"],
        "planned_or_applied": changed if apply else planned,
        "database_written": bool(apply and changed),
        "backup": str(backup) if backup else None,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
