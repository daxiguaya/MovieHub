"""Read-only TMDB identity candidate audit for MovieHub's existing database.

The tool never writes to SQLite and never imports provider ratings or synopsis text.
It emits identity evidence only; candidates are not automatically linked.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import settings

TMDB_BASE_URL = "https://api.themoviedb.org/3"
USER_AGENT = "MovieHub/1.0 (+self-hosted identity audit)"
MAX_SEARCH_RESULTS = 20


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in value if char.isalnum())


def parse_names(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [value.strip()] if value.strip() else []
    if not isinstance(parsed, list):
        return []
    names = []
    for item in parsed:
        if isinstance(item, dict):
            item = item.get("name")
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


def read_movies(database_path: str | Path) -> tuple[list[dict[str, Any]], int]:
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MovieHub database does not exist: {path}")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "movies" not in tables:
            raise ValueError("Not a MovieHub database: movies table is missing")
        columns = {row["name"] for row in connection.execute('PRAGMA table_info("movies")')}
        required = {"id", "douban_id", "imdb_id", "tmdb_id", "title", "original_title", "year", "type", "directors"}
        missing = sorted(required - columns)
        if missing:
            raise ValueError("MovieHub movies table is missing columns: " + ", ".join(missing))
        total = connection.execute("SELECT COUNT(*) FROM movies WHERE tmdb_id IS NULL OR trim(tmdb_id) = ''").fetchone()[0]
        rows = connection.execute(
            """SELECT id, douban_id, imdb_id, title, original_title, year, type, directors
               FROM movies WHERE tmdb_id IS NULL OR trim(tmdb_id) = ''
               ORDER BY id"""
        ).fetchall()
        return ([{
            "movie_id": row["id"], "douban_id": row["douban_id"],
            "imdb_id": row["imdb_id"], "title": row["title"],
            "original_title": row["original_title"], "year": row["year"],
            "media_type": row["type"] if row["type"] in ("movie", "tv") else "movie",
            "directors": parse_names(row["directors"]),
        } for row in rows], total)
    finally:
        connection.close()


class TMDBLookup:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise ValueError("TMDB_API_READ_TOKEN is not configured")
        self.client = client or httpx.Client(
            base_url=TMDB_BASE_URL,
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT},
        )
        self.owns_client = client is None
        self.calls = 0

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Sequential requests and a conservative delay; stop rather than evade limits.
        if self.calls:
            time.sleep(0.25)
        response = self.client.get(endpoint, params=params or {})
        self.calls += 1
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise RuntimeError(f"TMDB rate limit reached (Retry-After: {retry_after}); stopped without retry")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TMDB returned an unexpected response")
        return payload

    def close(self) -> None:
        if self.owns_client:
            self.client.close()


def candidate_identity(candidate: dict[str, Any], media_type: str) -> tuple[set[str], int | None]:
    title_keys = ("title", "original_title") if media_type == "movie" else ("name", "original_name")
    titles = {normalize(candidate.get(key)) for key in title_keys if normalize(candidate.get(key))}
    date_value = candidate.get("release_date") or candidate.get("first_air_date") or ""
    year = int(date_value[:4]) if isinstance(date_value, str) and date_value[:4].isdigit() else None
    return titles, year


def audit_candidates(
    database_path: str | Path,
    token: str,
    limit: int = 25,
    lookup_factory: Callable[[str], TMDBLookup] = TMDBLookup,
) -> dict[str, Any]:
    movies, total_missing = read_movies(database_path)
    selected = movies if limit <= 0 else movies[:limit]
    lookup = lookup_factory(token)
    results: list[dict[str, Any]] = []
    try:
        for index, movie in enumerate(selected, 1):
            media_type = movie["media_type"]
            source_titles = {
                normalize(value) for value in (movie["title"], movie["original_title"])
                if normalize(value)
            }
            source_directors = {normalize(value) for value in movie["directors"] if normalize(value)}
            candidate_pool: dict[int, dict[str, Any]] = {}
            queries = list(dict.fromkeys(
                value.strip() for value in (movie["title"], movie["original_title"])
                if isinstance(value, str) and value.strip()
            ))
            errors: list[str] = []
            for query in queries:
                params: dict[str, Any] = {
                    "query": query, "language": "zh-CN", "include_adult": "false", "page": 1,
                }
                if movie["year"] is not None:
                    params["primary_release_year" if media_type == "movie" else "first_air_date_year"] = movie["year"]
                try:
                    payload = lookup.get(f"/search/{media_type}", params)
                except Exception as exc:
                    errors.append(type(exc).__name__ + ": " + str(exc)[:180])
                    break
                for candidate in payload.get("results", [])[:MAX_SEARCH_RESULTS]:
                    if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), int):
                        continue
                    titles, candidate_year = candidate_identity(candidate, media_type)
                    if not source_titles.intersection(titles):
                        continue
                    candidate_pool[candidate["id"]] = {
                        "tmdb_id": candidate["id"],
                        "title": candidate.get("title") or candidate.get("name"),
                        "original_title": candidate.get("original_title") or candidate.get("original_name"),
                        "year": candidate_year,
                    }

            verified: list[dict[str, Any]] = []
            review_candidates: list[dict[str, Any]] = []
            for candidate in candidate_pool.values():
                evidence = []
                title_match = bool(source_titles.intersection({
                    normalize(candidate.get("title")), normalize(candidate.get("original_title"))
                } - {""}))
                if title_match:
                    evidence.append("normalized_title_exact")
                if movie["year"] is not None and candidate["year"] == movie["year"]:
                    evidence.append("year_exact")
                elif movie["year"] is None:
                    evidence.append("source_year_missing")
                else:
                    evidence.append("year_mismatch_or_missing")

                if not title_match or (movie["year"] is not None and candidate["year"] != movie["year"]):
                    review_candidates.append({**candidate, "evidence": evidence + ["not_verified"]})
                    continue

                try:
                    detail = lookup.get(
                        f"/{media_type}/{candidate['tmdb_id']}",
                        {"language": "zh-CN", "append_to_response": "credits"},
                    )
                except Exception as exc:
                    errors.append(type(exc).__name__ + ": " + str(exc)[:180])
                    review_candidates.append({**candidate, "evidence": evidence + ["detail_lookup_failed"]})
                    continue
                credits = detail.get("credits") if isinstance(detail.get("credits"), dict) else {}
                crew = credits.get("crew") if isinstance(credits.get("crew"), list) else []
                tmdb_directors = {
                    normalize(person.get("name")) for person in crew
                    if isinstance(person, dict)
                    and (person.get("job") == "Director" or (media_type == "tv" and person.get("department") == "Directing"))
                    and normalize(person.get("name"))
                }
                if source_directors and source_directors.intersection(tmdb_directors):
                    evidence.append("director_exact")
                    verified.append({**candidate, "directors": sorted(tmdb_directors), "evidence": evidence})
                elif source_directors:
                    evidence.append("director_conflict_or_unavailable")
                    review_candidates.append({**candidate, "directors": sorted(tmdb_directors), "evidence": evidence})
                else:
                    evidence.append("source_director_missing")
                    review_candidates.append({**candidate, "directors": sorted(tmdb_directors), "evidence": evidence})

            if len(verified) == 1 and not review_candidates and not errors:
                status = "verified_candidate"
            elif verified or review_candidates:
                status = "needs_review"
            else:
                status = "no_match"
            results.append({
                "movie_id": movie["movie_id"], "douban_id": movie["douban_id"],
                "title": movie["title"], "original_title": movie["original_title"],
                "year": movie["year"], "media_type": media_type,
                "source_directors": movie["directors"], "status": status,
                "verified_candidates": verified, "review_candidates": review_candidates,
                "errors": errors,
            })
            print(f"[{index}/{len(selected)}] movie_id={movie['movie_id']} status={status}", file=sys.stderr)
    finally:
        lookup.close()

    counts = {key: sum(1 for item in results if item["status"] == key)
              for key in ("verified_candidate", "needs_review", "no_match")}
    return {
        "report_version": 1, "read_only": True, "database": str(Path(database_path).expanduser().resolve()),
        "total_missing_tmdb_id": total_missing, "processed": len(selected),
        "remaining_not_processed": max(0, total_missing - len(selected)),
        "counts": counts, "tmdb_requests": lookup.calls,
        "safety": [
            "SQLite opened with mode=ro and PRAGMA query_only=ON.",
            "No database rows, IDs, ratings, rating counts, or synopsis text were modified or exported.",
            "TMDB candidates are evidence for manual review only; no identity is persisted.",
            "TMDB rate limiting stops the audit; requests are sequential with a 250ms minimum delay.",
        ],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only TMDB identity candidate audit (no DB writes).")
    parser.add_argument("--db", required=True, help="MovieHub movies.db path")
    parser.add_argument("--limit", type=int, default=25, help="Maximum records to inspect; use 0 for all missing TMDB IDs")
    parser.add_argument("--output", help="Optional JSON report path; stdout is used when omitted")
    args = parser.parse_args()
    try:
        report = audit_candidates(args.db, settings.tmdb_api_read_token, args.limit)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).expanduser().write_text(rendered + "\n", encoding="utf-8")
            print(f"Report written to {args.output}", file=sys.stderr)
        else:
            print(rendered)
    except Exception as exc:
        print(f"TMDB candidate audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
