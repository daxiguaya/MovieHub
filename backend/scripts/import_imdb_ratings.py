"""Import official IMDb title ratings for exact local IMDb IDs only.

IMDb data is licensed for personal, non-commercial use. Keep the downloaded
TSV and the resulting MovieHub database private; never redistribute either.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import (
    Movie,
    MovieMetadataProvenance,
    database_is_ready,
    get_db_path,
)

IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
IMDB_ID_PATTERN = re.compile(r"tt[0-9]{7,12}")


def iter_matching_ratings(
    input_path: str | Path,
    wanted_ids: set[str],
) -> Iterator[tuple[str, float, int]]:
    """Stream the official TSV and yield only exact local IMDb ID matches."""
    path = Path(input_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"IMDb ratings TSV does not exist: {path}")

    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"tconst", "averageRating", "numVotes"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                "IMDb ratings file must contain tconst, averageRating and numVotes columns"
            )

        seen: set[str] = set()
        for row in reader:
            imdb_id = (row.get("tconst") or "").strip()
            if imdb_id not in wanted_ids:
                continue
            if not IMDB_ID_PATTERN.fullmatch(imdb_id):
                raise ValueError(f"Invalid IMDb title ID in ratings file: {imdb_id!r}")
            if imdb_id in seen:
                raise ValueError(f"Duplicate IMDb ratings row for {imdb_id}")
            seen.add(imdb_id)

            try:
                rating = float(row["averageRating"])
                vote_count = int(row["numVotes"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid rating row for {imdb_id}") from exc
            if not 0 <= rating <= 10 or vote_count < 0:
                raise ValueError(f"Out-of-range IMDb rating row for {imdb_id}")
            yield imdb_id, rating, vote_count


def create_verified_backup(database_path: Path) -> Path:
    """Create and integrity-check a SQLite online backup before writes."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    backup_path = database_path.with_name(
        f"{database_path.stem}.pre-imdb-ratings-{stamp}.sqlite3"
    )
    source = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=60)
    destination = sqlite3.connect(str(backup_path), timeout=60)
    try:
        source.backup(destination)
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()

    check = sqlite3.connect(str(backup_path), timeout=60)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("IMDb pre-import backup failed SQLite integrity_check")
    finally:
        check.close()
    return backup_path


def import_imdb_ratings(
    input_path: str | Path,
    *,
    database_path: str | Path | None = None,
    apply: bool = False,
) -> dict:
    """Dry-run by default; update only exact IMDb-ID matches when apply=True."""
    db_path = Path(database_path or get_db_path()).expanduser().resolve()
    if not database_is_ready(db_path):
        raise RuntimeError(
            "MovieHub database is not ready at schema v5. Run the reviewed migration first."
        )

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"timeout": 60})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            total_local_movies = db.query(Movie).count()
            movies = db.scalars(
                select(Movie).where(Movie.imdb_id.is_not(None))
            ).all()
            movie_by_imdb = {
                movie.imdb_id: movie
                for movie in movies
                if movie.imdb_id and IMDB_ID_PATTERN.fullmatch(movie.imdb_id)
            }
            if not movie_by_imdb:
                return {
                    "valid": True,
                    "applied": False,
                    "total_local_movies": total_local_movies,
                    "local_movies_with_imdb_id": 0,
                    "imdb_id_coverage_percent": 0.0,
                    "matched": 0,
                    "unmatched": 0,
                    "message": "No local Movie records have a valid IMDb title ID.",
                }

            ratings = list(iter_matching_ratings(input_path, set(movie_by_imdb)))
            matched_ids = {item[0] for item in ratings}
            changed_ids = {
                imdb_id for imdb_id, rating, votes in ratings
                if movie_by_imdb[imdb_id].imdb_rating != rating
                or movie_by_imdb[imdb_id].imdb_rating_count != votes
            }
            unchanged_ids = matched_ids - changed_ids
            summary = {
                "valid": True,
                "applied": False,
                "dataset": IMDB_RATINGS_URL,
                "total_local_movies": total_local_movies,
                "local_movies_with_imdb_id": len(movie_by_imdb),
                "imdb_id_coverage_percent": round(len(movie_by_imdb) * 100 / total_local_movies, 2) if total_local_movies else 0.0,
                "matched": len(ratings),
                "changed": len(changed_ids),
                "unchanged": len(unchanged_ids),
                "missing_in_snapshot": len(movie_by_imdb) - len(matched_ids),
                "unmatched": len(movie_by_imdb) - len(matched_ids),
                "matched_examples": sorted(matched_ids)[:10],
                "unmatched_examples": sorted(set(movie_by_imdb) - matched_ids)[:10],
            }
            if not apply:
                return summary
            if not ratings:
                raise RuntimeError("No exact IMDb IDs matched; refusing an empty import.")

            now = datetime.utcnow()
            provenance_added = 0
            provenance_rows = []
            for imdb_id, rating, vote_count in ratings:
                movie = movie_by_imdb[imdb_id]
                for field_name, value in (
                    ("imdb_rating", f"{rating:.1f}"),
                    ("imdb_rating_count", str(vote_count)),
                ):
                    digest = hashlib.sha256(f"{imdb_id}\t{value}".encode("utf-8")).hexdigest()
                    existing = db.scalar(
                        select(MovieMetadataProvenance.id).where(
                            MovieMetadataProvenance.movie_id == movie.id,
                            MovieMetadataProvenance.field_name == field_name,
                            MovieMetadataProvenance.source == "imdb",
                            MovieMetadataProvenance.source_url == IMDB_RATINGS_URL,
                            MovieMetadataProvenance.value_sha256 == digest,
                        ).limit(1)
                    )
                    if existing is None:
                        provenance_rows.append(
                            MovieMetadataProvenance(
                                movie_id=movie.id,
                                field_name=field_name,
                                source="imdb",
                                source_url=IMDB_RATINGS_URL,
                                observed_at=now,
                                value_sha256=digest,
                            )
                        )
                        provenance_added += 1

            # Create a backup only when this run will mutate the database.
            backup_path = (
                create_verified_backup(db_path)
                if changed_ids or provenance_rows
                else None
            )
            for imdb_id, rating, vote_count in ratings:
                if imdb_id not in changed_ids:
                    continue
                movie = movie_by_imdb[imdb_id]
                movie.imdb_rating = rating
                movie.imdb_rating_count = vote_count

            if provenance_rows:
                db.add_all(provenance_rows)
            db.commit()
            summary.update({
                "applied": True,
                "updated": len(changed_ids),
                "changed": len(changed_ids),
                "unchanged": len(unchanged_ids),
                "provenance_added": provenance_added,
                "backup": str(backup_path) if backup_path else None,
                "integrity_check": "backup verified before import; database transaction committed",
            })
            return summary
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import IMDb title ratings for exact local IMDb IDs (dry-run by default)."
    )
    parser.add_argument("--input", required=True, help="Official title.ratings.tsv.gz or TSV file")
    parser.add_argument("--db", type=Path, default=None, help="MovieHub database path")
    parser.add_argument("--apply", action="store_true", help="Write ratings after a successful dry-run")
    args = parser.parse_args()
    try:
        result = import_imdb_ratings(args.input, database_path=args.db, apply=args.apply)
    except Exception as exc:
        print(f"IMDb ratings import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
