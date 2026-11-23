
"""Non-destructive MovieHub importer for Douban Scout SQLite databases."""

import json
import logging
import math
from itertools import islice
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache import cache_manager
from app.database import (
    Genre,
    Movie,
    MovieGenre,
    MoviePoster,
    MovieRegion,
    Region,
    SessionLocal,
)
from app.metadata_constants import VALID_GENRES, VALID_REGIONS
from app.schemas import ImportStatus

logger = logging.getLogger("moviehub.import")

SOURCE_ROW_SQL = """
SELECT
    douban_id,
    imdb_id,
    douban_title,
    year,
    rating,
    raw_data,
    type,
    update_time
FROM item
WHERE type IN ('movie', 'tv')
ORDER BY douban_id
"""


class ImportService:
    """Background, non-destructive importer."""

    _instance: "ImportService | None" = None
    _instance_lock = threading.Lock()

    _BATCH_SIZE = 500
    _MAX_ERROR_LOGS = 10

    VALID_GENRES: ClassVar[set[str]] = set(VALID_GENRES)
    VALID_REGIONS: ClassVar[set[str]] = set(VALID_REGIONS)

    _SORTED_GENRES: ClassVar[list[str]] = sorted(
        VALID_GENRES,
        key=len,
        reverse=True,
    )
    _SORTED_REGIONS: ClassVar[list[str]] = sorted(
        VALID_REGIONS,
        key=len,
        reverse=True,
    )

    def __new__(cls) -> "ImportService":
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._status = ImportStatus(status="idle")
                instance._status_lock = threading.RLock()
                instance._run_lock = threading.Lock()
                cls._instance = instance
        return cls._instance

    @property
    def status(self) -> ImportStatus:
        """Return a detached copy of the current import status."""
        with self._status_lock:
            return self._status.model_copy(deep=True)

    def start_import(
        self,
        source_path: str,
        force_full: bool = False,
    ) -> ImportStatus:
        """Start a background import.

        force_full means reprocess every source record. It does not mean
        deleting or replacing the target database.
        """
        path = Path(source_path).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"Source database not found: {path}")

        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Import already in progress")

        try:
            with self._status_lock:
                self._status = ImportStatus(
                    status="running",
                    processed=0,
                    total=0,
                    percentage=0.0,
                    message="Import started",
                    started_at=datetime.now(),
                )

            thread = threading.Thread(
                target=self._run_import,
                args=(path, force_full),
                name="moviehub-import",
                daemon=True,
            )
            thread.start()

            return self.status

        except Exception:
            self._run_lock.release()
            raise

    def _set_progress(
        self,
        processed: int,
        total: int,
        message: str | None = None,
    ) -> None:
        with self._status_lock:
            self._status.processed = processed
            self._status.total = total
            self._status.percentage = (
                round(processed * 100.0 / total, 2)
                if total
                else 100.0
            )
            if message is not None:
                self._status.message = message

    def _finish(
        self,
        status: str,
        message: str | None = None,
    ) -> None:
        with self._status_lock:
            self._status.status = status
            self._status.completed_at = datetime.now()
            if message is not None:
                self._status.message = message

    def _run_import(
        self,
        source_path: Path,
        force_full: bool,
    ) -> None:
        source_conn: sqlite3.Connection | None = None
        committed_batches = 0

        try:
            logger.info(
                "Starting MovieHub import: source=%s force_full=%s batch_size=%s",
                source_path,
                force_full,
                self._BATCH_SIZE,
            )

            # Read-only, but deliberately not immutable: SQLite may need the
            # source database's WAL file to present a consistent snapshot.
            source_uri = source_path.as_uri() + "?mode=ro"
            source_conn = sqlite3.connect(
                source_uri,
                uri=True,
                timeout=30,
            )
            source_conn.row_factory = sqlite3.Row
            self._validate_source(source_conn, reject_duplicate_ids=True)

            total = source_conn.execute(
                "SELECT COUNT(*) FROM item WHERE type IN ('movie', 'tv')"
            ).fetchone()[0]
            if total <= 0:
                raise ValueError("Source database contains no movie or TV records")

            self._set_progress(0, total, "Reading source database")
            processed = 0
            skipped = 0
            imported = 0
            error_logs = 0
            cursor = source_conn.execute(SOURCE_ROW_SQL)

            with SessionLocal() as db:
                while True:
                    rows = list(islice(cursor, self._BATCH_SIZE))
                    if not rows:
                        break

                    # Commit bounded batches instead of holding one SQLite
                    # writer transaction for the entire Scout catalogue.
                    # A failed batch rolls back as a unit; committed batches
                    # remain safe to retry because the importer is idempotent.
                    with db.begin():
                        genre_map = self._ensure_genres(db)
                        region_map = self._ensure_regions(db)

                        for row in rows:
                            try:
                                with db.begin_nested():
                                    changed = self._upsert_source_row(
                                        db=db,
                                        row=row,
                                        genre_map=genre_map,
                                        region_map=region_map,
                                        force_full=force_full,
                                    )
                                if changed:
                                    imported += 1
                                else:
                                    skipped += 1
                            except Exception:
                                genre_map = {
                                    item.name: item.id
                                    for item in db.scalars(select(Genre)).all()
                                }
                                region_map = {
                                    item.name: item.id
                                    for item in db.scalars(select(Region)).all()
                                }
                                skipped += 1
                                if error_logs < self._MAX_ERROR_LOGS:
                                    logger.exception(
                                        "Failed to process source record douban_id=%s",
                                        row["douban_id"],
                                    )
                                    error_logs += 1
                            processed += 1

                    committed_batches += 1
                    self._set_progress(
                        processed,
                        total,
                        f"Processed {processed} of {total} records",
                    )

            logger.info(
                "Import committed: processed=%s imported=%s skipped=%s batches=%s force_full=%s",
                processed,
                imported,
                skipped,
                committed_batches,
                force_full,
            )

            if imported:
                cache_manager.clear()

            self._set_progress(
                processed,
                total,
                f"Import completed; imported {imported}, skipped {skipped}",
            )
            self._finish(
                "completed",
                f"Import completed; imported {imported}, skipped {skipped}",
            )

        except Exception:
            logger.exception(
                "MovieHub import failed after %s committed batches",
                committed_batches,
            )
            # Earlier committed batches are durable and safe to reprocess.
            if committed_batches:
                try:
                    cache_manager.clear()
                except Exception:
                    logger.exception("Failed to clear caches after partial import")
            self._finish(
                "failed",
                "Import failed. Earlier batches, if any, were committed; retry is safe. "
                "Check the backend log for details.",
            )

        finally:
            if source_conn is not None:
                source_conn.close()
            self._run_lock.release()

    @staticmethod
    def _validate_source(
        conn: sqlite3.Connection,
        reject_duplicate_ids: bool = False,
    ) -> None:
        """Check that the source database has the expected item table."""
        result = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'item'
            """
        ).fetchone()

        if result is None:
            raise ValueError("Source database does not contain an item table")

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(item)").fetchall()
        }

        required = {
            "douban_id",
            "imdb_id",
            "douban_title",
            "year",
            "rating",
            "raw_data",
            "type",
            "update_time",
        }

        missing = required - columns
        if missing:
            raise ValueError(
                "Source item table is missing required columns: "
                + ", ".join(sorted(missing))
            )

        # A Scout export must identify each imported subject exactly once.
        # Duplicate IDs make the eventual upsert depend on SQLite row order
        # and can silently replace one record with another.
        if not reject_duplicate_ids:
            return

        duplicate = conn.execute(
            """
            SELECT douban_id, COUNT(*) AS row_count
            FROM item
            WHERE type IN ('movie', 'tv')
              AND douban_id IS NOT NULL
            GROUP BY douban_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate is not None:
            raise ValueError(
                "Source database contains duplicate Douban IDs: "
                f"{duplicate['douban_id']} ({duplicate['row_count']} rows)"
            )

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if not value:
            return {}

        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}

        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """Normalize a list of strings or common metadata objects."""
        if not isinstance(value, list):
            return []

        result: list[str] = []

        for item in value:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = str(
                    item.get("name")
                    or item.get("title")
                    or ""
                ).strip()
            else:
                continue

            if name and name not in result:
                result.append(name)

        return result

    @staticmethod
    def _extract_metadata(
        value: str,
        is_genre: bool,
        include_unknown: bool = False,
    ) -> set[str]:
        """Extract whitelisted genres or regions from text."""
        if not value:
            return set()

        segments = re.split(r"[/|\\,，、]", value)

        whitelist = (
            ImportService._SORTED_GENRES
            if is_genre
            else ImportService._SORTED_REGIONS
        )
        valid = (
            ImportService.VALID_GENRES
            if is_genre
            else ImportService.VALID_REGIONS
        )

        found: set[str] = set()

        for segment in segments:
            cleaned = segment.strip()
            if not cleaned:
                continue

            matched = False
            if cleaned in valid:
                found.add(cleaned)
                matched = True
            else:
                for item in whitelist:
                    if item and item in cleaned:
                        found.add(item)
                        matched = True

            # Structured genres/countries fields are authoritative source data.
            # Keep new/less-common values instead of silently dropping them.
            if (
                include_unknown
                and not matched
                and len(cleaned) <= 32
                and not any(ord(char) < 32 for char in cleaned)
                and not cleaned.lower().startswith(("http://", "https://"))
            ):
                found.add(cleaned)

        return found

    def _extract_detail(
        self,
        raw_data: Any,
    ) -> dict[str, Any]:
        """Extract optional metadata from Scout raw_data."""
        payload = self._parse_json(raw_data)
        detail = payload.get("detail", {})

        if not isinstance(detail, dict):
            detail = {}

        rating_info = detail.get("rating", {})
        if not isinstance(rating_info, dict):
            rating_info = {}

        rating_count = (
            rating_info.get("count")
            or detail.get("vote_count")
            or 0
        )

        pic = detail.get("pic", {})
        if not isinstance(pic, dict):
            pic = {}

        posters = set()
        for key in ("normal", "large"):
            url = pic.get(key)
            if isinstance(url, str) and url.strip():
                posters.add(url.strip())

        cover_url = detail.get("cover_url")
        if isinstance(cover_url, str) and cover_url.strip():
            posters.add(cover_url.strip())

        genres: set[str] = set()
        regions: set[str] = set()

        for value in (
            detail.get("genres", [])
            + detail.get("types", [])
            if isinstance(detail.get("genres", []), list)
            and isinstance(detail.get("types", []), list)
            else []
        ):
            if isinstance(value, str):
                genres.update(self._extract_metadata(value, True, include_unknown=True))

        for value in (
            detail.get("countries", [])
            + detail.get("regions", [])
            if isinstance(detail.get("countries", []), list)
            and isinstance(detail.get("regions", []), list)
            else []
        ):
            if isinstance(value, str):
                regions.update(self._extract_metadata(value, False, include_unknown=True))

        subtitle = (
            detail.get("card_subtitle")
            or detail.get("subtitle")
            or ""
        )

        if isinstance(subtitle, str) and subtitle:
            genres.update(self._extract_metadata(subtitle, True))

            parts = [part.strip() for part in subtitle.split("/")]
            start_index = 1 if parts and re.match(r"^\d{4}$", parts[0]) else 0

            genre_index = next(
                (
                    index
                    for index in range(start_index, len(parts))
                    if self._extract_metadata(parts[index], True)
                ),
                -1,
            )

            if genre_index > start_index:
                for part in parts[start_index:genre_index]:
                    regions.update(self._extract_metadata(part, False))
            elif genre_index == -1 and len(parts) > start_index:
                regions.update(
                    self._extract_metadata(parts[start_index], False)
                )

        directors = self._string_list(detail.get("directors", []))
        actors = self._string_list(detail.get("actors", []))

        original_title = (
            detail.get("original_title")
            or detail.get("original_name")
        )
        overview = (
            detail.get("summary")
            or detail.get("intro")
            or detail.get("description")
        )

        douban_url = detail.get("url") or detail.get("share_url")

        return {
            "rating_count": self._safe_int(rating_count, default=0),
            "posters": sorted(posters),
            "genres": sorted(genres),
            "regions": sorted(regions),
            "directors": directors,
            "actors": actors,
            "original_title": self._safe_string(original_title),
            "overview": self._safe_string(overview),
            "douban_url": self._safe_string(douban_url),
        }

    @staticmethod
    def _safe_int(value: Any, default: int | None = None) -> int | None:
        # bool subclasses int; fractional floats must not be truncated.
        if value is None or value == "" or isinstance(value, bool):
            return default
        if isinstance(value, float) and not value.is_integer():
            return default
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _safe_rating(value: Any) -> float | None:
        if value is None or value == "" or isinstance(value, bool):
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(rating) or not 0 <= rating <= 10:
            return None
        return rating

    @staticmethod
    def _safe_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _ensure_genres(self, db: Session) -> dict[str, int]:
        existing = {
            item.name: item.id
            for item in db.scalars(select(Genre)).all()
        }

        for name in sorted(self.VALID_GENRES - existing.keys()):
            db.add(Genre(name=name))

        db.flush()

        return {
            item.name: item.id
            for item in db.scalars(select(Genre)).all()
        }

    def _ensure_regions(self, db: Session) -> dict[str, int]:
        existing = {
            item.name: item.id
            for item in db.scalars(select(Region)).all()
        }

        for name in sorted(self.VALID_REGIONS - existing.keys()):
            db.add(Region(name=name))

        db.flush()

        return {
            item.name: item.id
            for item in db.scalars(select(Region)).all()
        }

    def _upsert_source_row(
        self,
        db: Session,
        row: sqlite3.Row,
        genre_map: dict[str, int],
        region_map: dict[str, int],
        force_full: bool = False,
    ) -> bool:
        """Upsert one movie while preserving data absent from this source.

        Incremental imports skip records whose Scout update_time is not newer
        than MovieHub's last imported source timestamp. force_full bypasses
        this check and reprocesses every valid source record.
        """
        douban_id = self._safe_string(row["douban_id"])
        title = self._safe_string(row["douban_title"])

        if not douban_id or not douban_id.isdigit() or not title:
            return False

        detail = self._extract_detail(row["raw_data"])

        movie = db.scalar(
            select(Movie).where(Movie.douban_id == douban_id)
        )

        if movie is not None and not force_full:
            source_updated_at = self._safe_int(row["update_time"])
            if (
                source_updated_at is not None
                and movie.updated_at is not None
                and source_updated_at <= movie.updated_at
            ):
                return False

        if movie is None:
            movie = Movie(
                douban_id=douban_id,
                title=title,
                type=row["type"],
                rating_count=0,
            )
            db.add(movie)

        # Update fields for which the source has a meaningful value.
        movie.title = title
        movie.type = row["type"]

        year = self._safe_int(row["year"])
        rating = self._safe_rating(row["rating"])

        if year is not None and 1870 <= year <= 2200:
            movie.year = year

        if rating is not None:
            movie.rating = rating

        imdb_id = self._safe_string(row["imdb_id"])
        if imdb_id:
            movie.imdb_id = imdb_id

        update_time = self._safe_int(row["update_time"])
        if update_time is not None:
            movie.updated_at = update_time

        if detail["rating_count"] > 0:
            movie.rating_count = detail["rating_count"]

        if detail["original_title"]:
            movie.original_title = detail["original_title"]

        if detail["overview"]:
            movie.overview = detail["overview"]

        if detail["douban_url"]:
            movie.douban_url = detail["douban_url"]

        if detail["directors"]:
            movie.directors = json.dumps(
                detail["directors"],
                ensure_ascii=False,
            )

        if detail["actors"]:
            movie.actors = json.dumps(
                detail["actors"],
                ensure_ascii=False,
            )

        db.flush()

        # Only replace associations when the source actually supplied values.
        # An incomplete source record must not erase richer existing metadata.
        if detail["genres"]:
            for name in detail["genres"]:
                if name not in genre_map:
                    genre = db.scalar(select(Genre).where(Genre.name == name))
                    if genre is None:
                        genre = Genre(name=name)
                        db.add(genre)
                        db.flush()
                    genre_map[name] = genre.id

            genre_ids = {
                genre_map[name]
                for name in detail["genres"]
                if name in genre_map
            }

            db.query(MovieGenre).filter(
                MovieGenre.movie_id == movie.id
            ).delete(synchronize_session=False)

            for genre_id in genre_ids:
                db.add(
                    MovieGenre(
                        movie_id=movie.id,
                        genre_id=genre_id,
                    )
                )

        if detail["regions"]:
            for name in detail["regions"]:
                if name not in region_map:
                    region = db.scalar(select(Region).where(Region.name == name))
                    if region is None:
                        region = Region(name=name)
                        db.add(region)
                        db.flush()
                    region_map[name] = region.id

            region_ids = {
                region_map[name]
                for name in detail["regions"]
                if name in region_map
            }

            db.query(MovieRegion).filter(
                MovieRegion.movie_id == movie.id
            ).delete(synchronize_session=False)

            for region_id in region_ids:
                db.add(
                    MovieRegion(
                        movie_id=movie.id,
                        region_id=region_id,
                    )
                )

        # Posters are additive: preserve existing URLs from other sources.
        if detail["posters"]:
            existing_posters = set(
                db.scalars(
                    select(MoviePoster.url).where(
                        MoviePoster.movie_id == movie.id
                    )
                ).all()
            )

            for url in detail["posters"]:
                if url not in existing_posters:
                    db.add(
                        MoviePoster(
                            movie_id=movie.id,
                            url=url,
                        )
                    )

        return True


import_service = ImportService()

