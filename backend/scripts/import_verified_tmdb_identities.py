"""Safely apply only uniquely verified TMDB identity candidates from an audit report.

Default mode is a read-only dry run. Applying requires --apply and creates a
verified SQLite backup before one all-or-nothing transaction. Only movies.tmdb_id
and its field-level provenance are written; Douban metadata is never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_plan(report_path: str | Path) -> list[dict[str, Any]]:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if report.get("report_version") != 1 or report.get("read_only") is not True:
        raise ValueError("Unsupported or non-read-only TMDB identity audit report")
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("Audit report results must be a list")

    plan: list[dict[str, Any]] = []
    seen_movies: set[int] = set()
    seen_tmdb: set[str] = set()
    for item in results:
        if not isinstance(item, dict) or item.get("status") != "verified_candidate":
            continue
        movie_id = item.get("movie_id")
        candidates = item.get("verified_candidates")
        if not isinstance(movie_id, int) or movie_id <= 0:
            raise ValueError("Verified result has an invalid MovieHub movie_id")
        if movie_id in seen_movies:
            raise ValueError(f"Duplicate MovieHub movie_id in report: {movie_id}")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError(f"Movie {movie_id} must have exactly one verified candidate")
        candidate = candidates[0]
        tmdb_id = candidate.get("tmdb_id") if isinstance(candidate, dict) else None
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            raise ValueError(f"Movie {movie_id} has an invalid TMDB ID")
        media_type = item.get("media_type")
        if media_type not in ("movie", "tv"):
            raise ValueError(f"Movie {movie_id} has an invalid media type")
        if str(tmdb_id) in seen_tmdb:
            raise ValueError(f"Duplicate TMDB ID in verified report: {tmdb_id}")
        if item.get("errors") or item.get("review_candidates"):
            raise ValueError(f"Movie {movie_id} has conflicting review/error evidence")
        seen_movies.add(movie_id)
        seen_tmdb.add(str(tmdb_id))
        plan.append({
            "movie_id": movie_id,
            "tmdb_id": str(tmdb_id),
            "media_type": media_type,
            "douban_id": item.get("douban_id"),
            "title": item.get("title"),
            "year": item.get("year"),
        })
    return plan


def integrity_check(path: Path) -> None:
    with sqlite3.connect(str(path), timeout=30) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result[0] if result else 'no result'}")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"SQLite foreign_key_check failed: {fk_errors[:5]}")


def create_backup(database: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.name}.pre-tmdb-identity-{stamp}.bak")
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(str(backup), timeout=30)
    try:
        source.backup(target)
        target.commit()
    except Exception:
        target.close()
        source.close()
        backup.unlink(missing_ok=True)
        raise
    else:
        target.close()
        source.close()
    integrity_check(backup)
    return backup


def prepare_changes(conn: sqlite3.Connection, plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    columns = {row[1] for row in conn.execute('PRAGMA table_info("movies")')}
    required = {"id", "douban_id", "tmdb_id", "title", "year", "type"}
    if not required.issubset(columns):
        raise ValueError("Not a compatible MovieHub movies table")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "movie_metadata_provenance" not in tables:
        raise ValueError("MovieHub provenance table is missing; refusing to write")

    changes: list[dict[str, Any]] = []
    already_applied: list[int] = []
    for entry in plan:
        row = conn.execute(
            "SELECT id, douban_id, tmdb_id, title, year, type FROM movies WHERE id=?",
            (entry["movie_id"],),
        ).fetchone()
        if row is None:
            raise ValueError(f"MovieHub movie_id no longer exists: {entry['movie_id']}")
        if row["douban_id"] != entry["douban_id"] or row["title"] != entry["title"] or row["year"] != entry["year"] or row["type"] != entry["media_type"]:
            raise ValueError(f"Audit report is stale or does not match MovieHub movie_id={entry['movie_id']}")
        existing = (row["tmdb_id"] or "").strip()
        if existing == entry["tmdb_id"]:
            already_applied.append(entry["movie_id"])
            continue
        if existing:
            raise ValueError(f"Movie {entry['movie_id']} already has a different TMDB ID: {existing}")
        owner = conn.execute("SELECT id FROM movies WHERE tmdb_id=?", (entry["tmdb_id"],)).fetchone()
        if owner is not None:
            raise ValueError(f"TMDB ID {entry['tmdb_id']} is already assigned to MovieHub movie_id={owner['id']}")
        changes.append(entry)
    return changes, already_applied


def apply_report(database_path: str | Path, report_path: str | Path, apply: bool = False) -> dict[str, Any]:
    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"MovieHub database does not exist: {database}")
    plan = load_plan(report_path)
    conn = sqlite3.connect(str(database), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        changes, already_applied = prepare_changes(conn, plan)
        conn.rollback()
    finally:
        conn.close()

    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "verified_candidates_in_report": len(plan),
        "would_update": len(changes),
        "already_applied": len(already_applied),
        "movie_ids_to_update": [item["movie_id"] for item in changes],
        "already_applied_movie_ids": already_applied,
        "database_written": False,
        "backup": None,
    }
    if not apply or not changes:
        return result

    backup = create_backup(database)
    conn = sqlite3.connect(str(database), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_changes, current_applied = prepare_changes(conn, plan)
        if current_changes != changes or current_applied != already_applied:
            raise RuntimeError("Database changed after preflight; refusing to apply stale plan")
        observed_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        for item in current_changes:
            cursor = conn.execute(
                "UPDATE movies SET tmdb_id=? WHERE id=? AND (tmdb_id IS NULL OR trim(tmdb_id)='')",
                (item["tmdb_id"], item["movie_id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Concurrent or unexpected update for movie_id={item['movie_id']}")
            value_hash = hashlib.sha256(item["tmdb_id"].encode("utf-8")).hexdigest()
            conn.execute(
                """INSERT INTO movie_metadata_provenance
                   (movie_id, field_name, source, source_url, observed_at, value_sha256)
                   VALUES (?, 'tmdb_id', 'tmdb', ?, ?, ?)""",
                (item["movie_id"], f"https://api.themoviedb.org/3/{item['media_type']}/{item['tmdb_id']}", observed_at, value_hash),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        integrity_check(database)
    except Exception:
        restore = sqlite3.connect(str(backup), timeout=60)
        target = sqlite3.connect(str(database), timeout=60)
        try:
            restore.backup(target)
            target.commit()
        finally:
            target.close()
            restore.close()
        raise

    result.update({
        "updated": len(changes),
        "database_written": True,
        "backup": str(backup),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply only uniquely verified TMDB IDs from a MovieHub audit report")
    parser.add_argument("--db", required=True, help="MovieHub movies.db path")
    parser.add_argument("--report", required=True, help="JSON report from audit_tmdb_identity_candidates")
    parser.add_argument("--apply", action="store_true", help="Create a backup and apply the verified IDs; default is dry-run")
    args = parser.parse_args()
    try:
        result = apply_report(args.db, args.report, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"TMDB identity import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
