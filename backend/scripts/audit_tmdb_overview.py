"""Read-only TMDB synopsis coverage audit; never writes to MovieHub SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from app.adapters.local_import import LocalImportAdapter
from app.adapters.tmdb_overview import TMDBOverviewClient


def load_snapshots(input_dir: str | Path, snapshot_date: str):
    directory = Path(input_dir).expanduser()
    if not directory.is_dir():
        raise ValueError("Snapshot input directory does not exist")
    snapshots = []
    for path in sorted(directory.rglob("*.json")):
        snapshot = LocalImportAdapter().load_snapshot(path)
        if snapshot.snapshot_date.isoformat() == snapshot_date:
            snapshots.append(snapshot)
    if not snapshots:
        raise ValueError(f"No normalized snapshots found for {snapshot_date}")
    return snapshots


def build_report(snapshots: list[Any], client: TMDBOverviewClient, languages: list[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    language_counts: dict[str, Counter[str]] = {
        language: Counter() for language in languages
    }

    unique_movies: dict[str, Any] = {}
    for snapshot in snapshots:
        for item in snapshot.movies:
            unique_movies.setdefault(item.douban_id, item)

    for douban_id, item in sorted(unique_movies.items()):
        for language in languages:
            try:
                result = client.lookup(item, language=language)
                status = result.status
                record = {
                    "douban_id": douban_id,
                    "title": item.title,
                    "year": item.year,
                    "media_type": item.type,
                    "language_requested": language,
                    "status": status,
                    "tmdb_id": result.tmdb_id,
                    "match_method": result.match_method,
                    "matched_title": result.matched_title,
                    "release_date": result.release_date,
                    "overview_language": result.language,
                    "overview_length": result.overview_length,
                    "overview_sha256": result.overview_sha256,
                    "source_url": result.source_url,
                    "candidate_count": result.candidate_count,
                }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise
                status = "provider_error"
                record = {
                    "douban_id": douban_id,
                    "title": item.title,
                    "year": item.year,
                    "media_type": item.type,
                    "language_requested": language,
                    "status": status,
                    "error_type": type(exc).__name__,
                }
            except Exception as exc:  # keep the audit moving; never leak token/header
                status = "provider_error"
                record = {
                    "douban_id": douban_id,
                    "title": item.title,
                    "year": item.year,
                    "media_type": item.type,
                    "language_requested": language,
                    "status": status,
                    "error_type": type(exc).__name__,
                }
            records.append(record)
            status_counts[status] += 1
            language_counts[language][status] += 1

    return {
        "mode": "read_only_dry_run",
        "provider": "tmdb",
        "movie_count": len(unique_movies),
        "language_count": len(languages),
        "record_count": len(records),
        "summary": dict(sorted(status_counts.items())),
        "by_language": {
            language: dict(sorted(counts.items()))
            for language, counts in language_counts.items()
        },
        "records": records,
        "notes": [
            "No synopsis text is included in this report.",
            "No MovieHub database is opened or modified.",
            "Only exact title/year matches or cross-checked IMDb-ID matches are accepted.",
            "Ambiguous, unmatched, year-mismatched and empty-overview records remain unaccepted.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit TMDB Chinese overview match/coverage without writing to a database."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--date", required=True, help="Snapshot date in YYYY-MM-DD format")
    parser.add_argument(
        "--language",
        action="append",
        dest="languages",
        help="TMDB locale to measure; repeat to compare (default: zh-CN)",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=0.3,
        help="Minimum delay between API requests in seconds (default: 0.3)",
    )
    args = parser.parse_args()

    token = os.environ.get("TMDB_API_READ_TOKEN", "").strip()
    if not token:
        print(
            "TMDB_API_READ_TOKEN is required; set it in the environment, never in source code.",
            file=sys.stderr,
        )
        return 2

    languages = args.languages or ["zh-CN"]
    if len(languages) != len(set(languages)):
        print("Duplicate --language values are not allowed", file=sys.stderr)
        return 2

    try:
        snapshots = load_snapshots(args.input_dir, args.date)
        with TMDBOverviewClient(
            token,
            min_interval_seconds=args.min_interval,
        ) as client:
            report = build_report(snapshots, client, languages)
    except Exception as exc:
        print(f"TMDB overview audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
