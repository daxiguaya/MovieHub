"""Import verified TMDB synopsis text into empty MovieHub overview fields.

This is an explicit, non-commercial-use workflow. It only fills empty fields,
records provenance, creates a verified SQLite backup before writing, and never
prints synopsis text or API credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app.adapters.tmdb_overview import TMDBOverviewClient
from app.database import Movie, MovieMetadataProvenance, SessionLocal, get_db_path


def _directors(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item.strip() for item in parsed if isinstance(item, str) and item.strip()]


def _backup_database(database_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"movies-before-tmdb-overviews-{stamp}.sqlite3"
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing backup")
    source = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(str(destination), timeout=30)
    try:
        source.backup(target)
        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("SQLite backup integrity_check failed")
    except Exception:
        target.close()
        source.close()
        destination.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    return destination


def _load_candidates() -> list[SimpleNamespace]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=170)
    candidates = []
    with SessionLocal() as db:
        rows = db.execute(select(Movie).order_by(Movie.id)).scalars().all()
        for row in rows:
            overview = (row.overview or "").strip()
            stale_tmdb_hash = None
            if overview:
                digest = hashlib.sha256(overview.encode("utf-8")).hexdigest()
                provenance = db.execute(
                    select(MovieMetadataProvenance).where(
                        MovieMetadataProvenance.movie_id == row.id,
                        MovieMetadataProvenance.field_name == "overview",
                        MovieMetadataProvenance.source == "tmdb",
                        MovieMetadataProvenance.value_sha256 == digest,
                    ).order_by(MovieMetadataProvenance.observed_at.desc())
                ).scalars().first()
                if provenance is None or provenance.observed_at > cutoff:
                    continue
                stale_tmdb_hash = digest
            candidates.append(SimpleNamespace(
                id=row.id,
                douban_id=row.douban_id,
                imdb_id=row.imdb_id,
                tmdb_id=row.tmdb_id,
                title=row.title,
                original_title=row.original_title,
                year=row.year,
                type=row.type,
                directors=_directors(row.directors),
                stale_tmdb_hash=stale_tmdb_hash,
            ))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch identity-verified TMDB overviews for movies with empty synopsis fields."
    )
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--min-interval", type=float, default=0.4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.apply:
        parser.error("Choose exactly one of --dry-run or --apply")
    if args.min_interval < 0.3:
        parser.error("--min-interval must be at least 0.3 seconds")

    token = os.environ.get("TMDB_API_READ_TOKEN", "").strip()
    if not token:
        print(json.dumps({"success": False, "error": "TMDB_API_READ_TOKEN is missing"}))
        return 2

    candidates = _load_candidates()
    results = {}
    counts: Counter[str] = Counter()
    with TMDBOverviewClient(token, min_interval_seconds=args.min_interval) as client:
        for item in candidates:
            try:
                result = client.lookup(item, language=args.language)
                counts[result.status] += 1
                results[item.id] = result
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    print(json.dumps({
                        "success": False,
                        "error": "TMDB authentication/permission failure",
                        "http_status": exc.response.status_code,
                        "database_written": False,
                    }))
                    return 3
                counts["provider_error"] += 1
            except Exception:
                counts["provider_error"] += 1

    report = {
        "success": True,
        "mode": "dry_run" if args.dry_run else "apply",
        "candidates": len(candidates),
        "matched_with_overview": sum(
            1 for result in results.values()
            if result.status == "overview_available" and result.overview
        ),
        "expired_tmdb_overviews": sum(
            1 for item in candidates if item.stale_tmdb_hash
        ),
        "statuses": dict(sorted(counts.items())),
        "database_written": False,
    }
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    database_path = Path(get_db_path()).expanduser().resolve()
    backup_dir = Path(os.environ.get("MOVIEHUB_BACKUP_DIR", "/backups"))
    backup_path = _backup_database(database_path, backup_dir)
    imported = 0
    skipped_changed = 0
    observed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    with SessionLocal() as db:
        with db.begin():
            for item in candidates:
                movie_id = item.id
                result = results.get(movie_id)
                movie = db.get(Movie, movie_id)
                if movie is None:
                    skipped_changed += 1
                    continue
                current_overview = (movie.overview or "").strip()
                if current_overview:
                    current_hash = hashlib.sha256(
                        current_overview.encode("utf-8")
                    ).hexdigest()
                    if not item.stale_tmdb_hash or current_hash != item.stale_tmdb_hash:
                        skipped_changed += 1
                        continue
                    # TMDB content is refreshed before the six-month cache limit.
                    if result is None or result.status != "overview_available" or not result.overview:
                        movie.overview = None
                        continue
                elif result is None or result.status != "overview_available" or not result.overview:
                    continue
                overview = result.overview.strip()
                digest = hashlib.sha256(overview.encode("utf-8")).hexdigest()
                existing = db.execute(
                    select(MovieMetadataProvenance).where(
                        MovieMetadataProvenance.movie_id == movie_id,
                        MovieMetadataProvenance.field_name == "overview",
                        MovieMetadataProvenance.source == "tmdb",
                        MovieMetadataProvenance.source_url == (result.source_url or ""),
                        MovieMetadataProvenance.value_sha256 == digest,
                    )
                ).scalars().first()
                movie.overview = overview
                if existing is None:
                    db.add(MovieMetadataProvenance(
                        movie_id=movie_id,
                        field_name="overview",
                        source="tmdb",
                        source_url=result.source_url or "",
                        observed_at=observed_at,
                        value_sha256=digest,
                    ))
                else:
                    existing.observed_at = observed_at
                imported += 1

    report.update({
        "database_written": True,
        "imported": imported,
        "expired_tmdb_overviews_purged": sum(
            1 for item in candidates
            if item.stale_tmdb_hash and (
                results.get(item.id) is None
                or results[item.id].status != "overview_available"
                or not results[item.id].overview
            )
        ),
        "skipped_changed": skipped_changed,
        "backup": str(backup_path),
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
