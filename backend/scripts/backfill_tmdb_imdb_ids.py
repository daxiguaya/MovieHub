"""Backfill exact IMDb title IDs from TMDB external_ids for existing local records.

This command is read-only by default. Use --apply only after reviewing the
preview. It never changes ratings, TMDB IDs, or movie identity fields.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database import (
    Movie,
    MovieMetadataProvenance,
    SessionLocal,
    database_is_ready,
    get_db_path,
)
from app.services.tmdb_client import DETAIL_TTL, tmdb_client

IMDB_ID_PATTERN = re.compile(r"tt[0-9]{7,12}")
SOURCE = "tmdb"
CONCURRENCY = 3


def valid_external_id(payload: Any, tmdb_id: str) -> str | None:
    """Return an IMDb ID only when the TMDB response identifies this exact item."""
    if not isinstance(payload, dict):
        return None
    try:
        response_id = int(payload.get("id"))
        expected_id = int(tmdb_id)
    except (TypeError, ValueError):
        return None
    if response_id != expected_id:
        return None
    imdb_id = payload.get("imdb_id")
    if not isinstance(imdb_id, str):
        return None
    imdb_id = imdb_id.strip()
    return imdb_id if IMDB_ID_PATTERN.fullmatch(imdb_id) else None


async def fetch_one(movie: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
    tmdb_id = movie["tmdb_id"]
    async with semaphore:
        try:
            payload = await tmdb_client.get_json(
                f'/{movie["type"]}/{int(tmdb_id)}/external_ids',
                {},
                DETAIL_TTL,
            )
        except Exception as exc:
            return {
                **movie,
                "status": "api_error",
                "error": type(exc).__name__,
            }

    imdb_id = valid_external_id(payload, tmdb_id)
    if imdb_id is None:
        return {**movie, "status": "no_valid_imdb_id"}
    return {**movie, "imdb_id": imdb_id, "status": "candidate"}


async def fetch_candidates(movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    return await asyncio.gather(*(fetch_one(movie, semaphore) for movie in movies))


def load_local_snapshot() -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read the local identity fields without holding a DB session during HTTP calls."""
    with SessionLocal() as db:
        all_movies = db.scalars(select(Movie).order_by(Movie.id)).all()
        existing_ids: dict[str, int] = {}
        pending: list[dict[str, Any]] = []
        counts = {
            "total": len(all_movies),
            "already_has_imdb_id": 0,
            "without_tmdb_id": 0,
            "eligible": 0,
        }
        for movie in all_movies:
            if movie.imdb_id and IMDB_ID_PATTERN.fullmatch(movie.imdb_id.strip()):
                counts["already_has_imdb_id"] += 1
                existing_ids[movie.imdb_id.strip()] = movie.id
                continue
            if not movie.tmdb_id or not str(movie.tmdb_id).isdigit():
                counts["without_tmdb_id"] += 1
                continue
            counts["eligible"] += 1
            pending.append({
                "movie_id": movie.id,
                "title": movie.title,
                "year": movie.year,
                "type": movie.type,
                "tmdb_id": str(movie.tmdb_id),
            })
        return pending, existing_ids


def classify_duplicates(
    results: list[dict[str, Any]],
    existing_ids: dict[str, int],
) -> list[dict[str, Any]]:
    """Reject every ambiguous IMDb ID rather than choosing an arbitrary movie."""
    counts: dict[str, int] = {}
    for row in results:
        if row.get("status") == "candidate":
            counts[row["imdb_id"]] = counts.get(row["imdb_id"], 0) + 1

    for row in results:
        if row.get("status") != "candidate":
            continue
        owner = existing_ids.get(row["imdb_id"])
        if counts[row["imdb_id"]] > 1 or (owner is not None and owner != row["movie_id"]):
            row["status"] = "duplicate_conflict"
            row.pop("imdb_id", None)
    return results


def create_verified_backup(database_path: Path) -> Path:
    """Create an SQLite online backup (including committed WAL data) and verify it."""
    import sqlite3

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    backup = database_path.with_name(
        f"{database_path.stem}.pre-tmdb-imdb-id-{stamp}.sqlite3"
    )
    source = sqlite3.connect(
        database_path.as_uri() + "?mode=ro", uri=True, timeout=60
    )
    destination = sqlite3.connect(str(backup), timeout=60)
    try:
        source.backup(destination)
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        backup.unlink(missing_ok=True)
        raise
    finally:
        try:
            destination.close()
        except Exception:
            pass
        source.close()

    check = sqlite3.connect(str(backup), timeout=60)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("Pre-update backup failed SQLite integrity_check")
    finally:
        check.close()
    return backup


def apply_candidates(
    results: list[dict[str, Any]],
    min_matched: int,
) -> dict[str, Any]:
    candidates = [row for row in results if row.get("status") == "candidate"]
    if len(candidates) < min_matched:
        raise RuntimeError(
            f"Quality gate failed: {len(candidates)} unique valid IMDb IDs; "
            f"minimum required is {min_matched}. No database changes made."
        )

    database_path = Path(get_db_path()).resolve()
    backup_path = create_verified_backup(database_path)
    updated = 0
    now = datetime.utcnow()

    with SessionLocal() as db:
        with db.begin():
            for row in candidates:
                movie = db.scalar(
                    select(Movie).where(Movie.id == row["movie_id"])
                )
                if movie is None:
                    continue
                # Recheck identity and never overwrite an existing IMDb ID.
                if (
                    movie.imdb_id
                    or str(movie.tmdb_id or "") != row["tmdb_id"]
                    or movie.type != row["type"]
                ):
                    continue
                conflict = db.scalar(
                    select(Movie.id).where(
                        Movie.imdb_id == row["imdb_id"],
                        Movie.id != movie.id,
                    ).limit(1)
                )
                if conflict is not None:
                    continue

                movie.imdb_id = row["imdb_id"]
                source_url = (
                    f'https://api.themoviedb.org/3/{row["type"]}/'
                    f'{row["tmdb_id"]}/external_ids'
                )
                digest = hashlib.sha256(
                    f'{row["tmdb_id"]}\t{row["imdb_id"]}'.encode("utf-8")
                ).hexdigest()
                provenance_exists = db.scalar(
                    select(MovieMetadataProvenance.id).where(
                        MovieMetadataProvenance.movie_id == movie.id,
                        MovieMetadataProvenance.field_name == "imdb_id",
                        MovieMetadataProvenance.source == SOURCE,
                        MovieMetadataProvenance.source_url == source_url,
                        MovieMetadataProvenance.value_sha256 == digest,
                    ).limit(1)
                )
                if provenance_exists is None:
                    db.add(MovieMetadataProvenance(
                        movie_id=movie.id,
                        field_name="imdb_id",
                        source=SOURCE,
                        source_url=source_url,
                        observed_at=now,
                        value_sha256=digest,
                    ))
                updated += 1

    return {
        "updated": updated,
        "backup": str(backup_path),
        "database": str(database_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only preview or verified TMDB-to-IMDb ID backfill."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write verified IMDb IDs to the MovieHub database.",
    )
    parser.add_argument(
        "--min-matched",
        type=int,
        default=10,
        help="Minimum unique valid IDs required for --apply (default: 10).",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Include every record in the JSON preview.",
    )
    args = parser.parse_args()

    if args.min_matched < 1:
        parser.error("--min-matched must be at least 1")

    database_path = Path(get_db_path()).resolve()
    if not database_is_ready(database_path):
        print("MovieHub database is not ready at the current schema.", file=sys.stderr)
        return 2

    pending, existing_ids = load_local_snapshot()
    results = classify_duplicates(
        asyncio.run(fetch_candidates(pending)),
        existing_ids,
    )
    counts: dict[str, int] = {}
    for row in results:
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1

    report: dict[str, Any] = {
        "read_only": not args.apply,
        "database": str(database_path),
        "local_total": sum(1 for _ in existing_ids) + len(pending),
        "already_has_valid_imdb_id": len(existing_ids),
        "eligible_with_tmdb_id": len(pending),
        "results": counts,
        "candidate_count": counts.get("candidate", 0),
        "quality_gate_minimum": args.min_matched,
        "records": results if args.show_all else results[:30],
    }

    if args.apply:
        try:
            report["apply_result"] = apply_candidates(results, args.min_matched)
            report["read_only"] = False
        except Exception as exc:
            report["apply_error"] = str(exc)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
