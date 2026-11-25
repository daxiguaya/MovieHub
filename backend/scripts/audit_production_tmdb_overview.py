"""Read-only TMDB overview coverage audit against the deployed MovieHub database.

The script reads MovieHub SQLite in read-only/query-only mode, uses only already
verified TMDB IDs, and reports overview availability metadata without returning
or persisting synopsis text. It is an audit, not an importer or license grant.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.adapters.tmdb_overview import TMDBOverviewClient


REQUIRED_COLUMNS = {
    "id", "douban_id", "tmdb_id", "imdb_id", "title",
    "original_title", "year", "type", "directors",
}


def _load_movies(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    columns = {
        row["name"] for row in connection.execute('PRAGMA table_info("movies")')
    }
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError("MovieHub movies table is missing columns: " + ", ".join(missing))
    rows = connection.execute(
        """
        SELECT id, douban_id, tmdb_id, imdb_id, title, original_title,
               year, type, directors
        FROM movies
        ORDER BY id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _error_status(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def audit_database(
    database_path: str | Path,
    client: Any,
    languages: list[str],
    limit: int = 0,
) -> dict[str, Any]:
    """Audit localized overview availability without changing SQLite or exposing text."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MovieHub database does not exist: {path}")
    if not languages or len(languages) != len(set(languages)):
        raise ValueError("At least one unique language is required")
    if limit < 0:
        raise ValueError("limit cannot be negative")

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        movies = _load_movies(connection)
        if limit:
            movies = movies[:limit]

        records: list[dict[str, Any]] = []
        summaries: dict[str, Counter[str]] = {
            language: Counter() for language in languages
        }
        for movie in movies:
            tmdb_id = str(movie.get("tmdb_id") or "").strip()
            year = movie.get("year")
            directors: list[str] = []
            try:
                parsed_directors = json.loads(movie.get("directors") or "[]")
                if isinstance(parsed_directors, list):
                    directors = [str(value) for value in parsed_directors if value]
            except (TypeError, ValueError):
                directors = []

            for language in languages:
                if not tmdb_id:
                    status = "no_tmdb_id"
                    result = None
                elif year is None:
                    # Do not weaken the existing ID + title + year identity check.
                    status = "insufficient_identity"
                    result = None
                else:
                    from types import SimpleNamespace

                    item = SimpleNamespace(
                        title=movie["title"],
                        original_title=movie.get("original_title"),
                        year=year,
                        type=movie["type"],
                        tmdb_id=tmdb_id,
                        imdb_id=movie.get("imdb_id"),
                        directors=directors,
                    )
                    try:
                        result = client.lookup(item, language=language)
                        status = result.status
                    except Exception as exc:
                        http_status = _error_status(exc)
                        if http_status in {401, 403, 429}:
                            raise RuntimeError(
                                f"TMDB returned HTTP {http_status}; audit stopped without bypass"
                            ) from exc
                        status = "provider_error"
                        result = None

                record = {
                    "movie_id": movie["id"],
                    "douban_id": movie.get("douban_id"),
                    "title": movie["title"],
                    "year": year,
                    "tmdb_id": tmdb_id or None,
                    "language_requested": language,
                    "status": status,
                }
                if result is not None:
                    record.update({
                        "match_method": result.match_method,
                        "matched_title": result.matched_title,
                        "overview_language": result.language,
                        "overview_length": result.overview_length,
                        "overview_sha256": result.overview_sha256,
                        "source_url": result.source_url,
                    })
                records.append(record)
                summaries[language][status] += 1

        return {
            "mode": "read_only_dry_run",
            "database": str(path),
            "movie_count": len(movies),
            "language_count": len(languages),
            "record_count": len(records),
            "summary": {
                language: dict(sorted(counts.items()))
                for language, counts in summaries.items()
            },
            "records": records,
            "safety": [
                "SQLite opened with mode=ro and PRAGMA query_only=ON.",
                "Only pre-verified TMDB IDs are queried; title and year are cross-checked.",
                "Records without a TMDB ID or year are not weakly matched.",
                "Synopsis text is never included in the report or written to SQLite.",
                "This audit does not authorize synopsis persistence or redistribution.",
            ],
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only TMDB overview coverage audit for the production MovieHub database."
    )
    parser.add_argument("--db", required=True, help="Path to MovieHub db/movies.db")
    parser.add_argument(
        "--language", action="append", dest="languages",
        help="TMDB locale; repeat to compare (default: zh-CN and zh-TW)",
    )
    parser.add_argument(
        "--min-interval", type=float, default=0.3,
        help="Minimum interval between TMDB requests in seconds (default: 0.3)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Audit only the first N database rows; 0 means all rows",
    )
    parser.add_argument("--output", help="Optional JSON report path; synopsis text is never included")
    args = parser.parse_args()

    token = os.environ.get("TMDB_API_READ_TOKEN", "").strip()
    if not token:
        print("TMDB_API_READ_TOKEN is required; token value is never printed.", file=sys.stderr)
        return 2
    languages = args.languages or ["zh-CN", "zh-TW"]
    if args.min_interval < 0 or args.limit < 0:
        print("--min-interval and --limit must be non-negative", file=sys.stderr)
        return 2

    try:
        with TMDBOverviewClient(
            token, min_interval_seconds=args.min_interval
        ) as client:
            report = audit_database(args.db, client, languages, args.limit)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
            print(json.dumps({
                "success": True,
                "mode": report["mode"],
                "movie_count": report["movie_count"],
                "record_count": report["record_count"],
                "output": str(output),
                "summary": report["summary"],
            }, ensure_ascii=False, indent=2))
        else:
            print(rendered)
    except Exception as exc:
        print(f"TMDB production overview audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
