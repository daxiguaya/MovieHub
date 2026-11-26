"""Build a private SQLite index from the complete official IMDb title ratings TSV.

The source file and derived index are for personal, non-commercial use only.
Never publish or redistribute the source dataset or this derived index.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from app.database import get_db_path
from scripts.import_imdb_ratings import IMDB_RATINGS_URL

IMDB_ID_PATTERN = re.compile(r"tt[0-9]{7,12}")
DEFAULT_MIN_ROWS = 100_000

def import_imdb_rating_index(input_path, *, database_path=None, apply=False, min_rows=DEFAULT_MIN_ROWS):
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"IMDb ratings snapshot does not exist: {source}")
    if min_rows < 1:
        raise ValueError("min_rows must be positive")
    target = Path(database_path or Path(get_db_path()).with_name("imdb-ratings.sqlite3")).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    fd, temporary_name = tempfile.mkstemp(prefix=".imdb-ratings-", suffix=".sqlite3", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    count = 0
    try:
        connection = sqlite3.connect(str(temporary), timeout=60)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("""CREATE TABLE ratings (
                imdb_id TEXT PRIMARY KEY,
                rating REAL NOT NULL CHECK(rating >= 0 AND rating <= 10),
                vote_count INTEGER NOT NULL CHECK(vote_count >= 0)
            ) WITHOUT ROWID""")
            connection.execute("""CREATE TABLE index_metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            ) WITHOUT ROWID""")
            opener = gzip.open if source.name.endswith(".gz") else open
            batch = []
            with opener(source, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                required = {"tconst", "averageRating", "numVotes"}
                if not reader.fieldnames or not required.issubset(reader.fieldnames):
                    raise ValueError("IMDb file must contain tconst, averageRating and numVotes")
                for line_number, row in enumerate(reader, start=2):
                    imdb_id = (row.get("tconst") or "").strip()
                    if not IMDB_ID_PATTERN.fullmatch(imdb_id):
                        raise ValueError(f"Invalid IMDb ID at line {line_number}")
                    try:
                        rating = float(row["averageRating"])
                        votes = int(row["numVotes"])
                    except (TypeError, ValueError, KeyError) as exc:
                        raise ValueError(f"Invalid IMDb rating at line {line_number}") from exc
                    if not 0 <= rating <= 10 or votes < 0:
                        raise ValueError(f"Out-of-range IMDb rating at line {line_number}")
                    batch.append((imdb_id, rating, votes))
                    if len(batch) >= 5000:
                        try:
                            connection.executemany("INSERT INTO ratings VALUES (?, ?, ?)", batch)
                        except sqlite3.IntegrityError as exc:
                            raise ValueError("Duplicate IMDb title ID in official ratings file") from exc
                        count += len(batch)
                        batch.clear()
                if batch:
                    try:
                        connection.executemany("INSERT INTO ratings VALUES (?, ?, ?)", batch)
                    except sqlite3.IntegrityError as exc:
                        raise ValueError("Duplicate IMDb title ID in official ratings file") from exc
                    count += len(batch)
            if count < min_rows:
                raise ValueError(f"IMDb index quality gate failed: {count} rows is below minimum {min_rows}")
            metadata = {
                "dataset_url": IMDB_RATINGS_URL,
                "source_sha256": source_hash,
                "row_count": str(count),
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }
            connection.executemany("INSERT INTO index_metadata VALUES (?, ?)", metadata.items())
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("Staged IMDb index failed integrity_check")
        finally:
            connection.close()
        summary = {
            "valid": True, "applied": False, "dataset": IMDB_RATINGS_URL,
            "source_sha256": source_hash, "indexed_titles": count,
            "minimum_required": min_rows, "database": str(target),
        }
        if not apply:
            return summary
        backup = None
        if target.is_file():
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
            backup = target.with_name(f"{target.stem}.pre-full-imdb-index-{stamp}.sqlite3")
            source_db = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=60)
            backup_db = sqlite3.connect(str(backup), timeout=60)
            try:
                source_db.backup(backup_db)
                check = backup_db.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError("Existing IMDb index backup failed integrity_check")
            except Exception:
                backup_db.close()
                source_db.close()
                backup.unlink(missing_ok=True)
                raise
            else:
                backup_db.close()
                source_db.close()
        os.replace(temporary, target)
        return {**summary, "applied": True, "backup": str(backup) if backup else None,
                "integrity_check": "staged index verified before atomic publication"}
    finally:
        temporary.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description="Build a private full IMDb ratings index (dry-run by default)")
    parser.add_argument("--input", required=True, help="Official title.ratings.tsv.gz or TSV")
    parser.add_argument("--db", type=Path, default=None, help="Output SQLite index path")
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--apply", action="store_true", help="Atomically publish the verified index")
    args = parser.parse_args()
    try:
        result = import_imdb_rating_index(args.input, database_path=args.db, apply=args.apply, min_rows=args.min_rows)
    except Exception as exc:
        print(f"Full IMDb index import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
