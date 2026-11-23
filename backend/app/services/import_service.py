
"""Non-destructive MovieHub importer for Douban Scout SQLite databases."""

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.cache import cache_manager
from app.database import (
    FTS_REBUILD_SQL,
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

        try:
            logger.info(
                "Starting MovieHub import: source=%s force_full=%s",
                source_path,
                force_full,
            )

            # Read-only, but deliberately not immutable:
            # SQLite may need to read a source database's WAL file.
            source_uri = source_path.as_uri() + "?mode=ro"
            source_conn = sqlite3.connect(
                source_uri,
                uri=True,
                timeout=30,
            )
            source_conn.row_factory = sqlite3.Row

            self._validate_source(source_conn)

            total = source_conn.execute(
                "SELECT COUNT(*) FROM item WHERE type IN ('movie', 'tv')"
            ).fetchone()[0]

            if total <= 0:
                raise ValueError("Source database contains no movie or TV records")

            self._set_progress(0, total, "Reading source database")

            processed = 0
            skipped = 0
            error_logs = 0

            with SessionLocal() as db:
                # A single transaction ensures a failed import does not leave
                # half-updated movie metadata or a stale FTS index.
                with db.begin():
                    genre_map = self._ensure_genres(db)
                    region_map = self._ensure_regions(db)

                    cursor = source_conn.execute(SOURCE_ROW_SQL)

                    for row in cursor:
                        try:
                            changed = self._upsert_source_row(
                                db=db,
                                row=row,
                                genre_map=genre_map,
                                region_map=region_map,
                            )
                            if not changed:
                                skipped += 1

                        except Exception:
                            skipped += 1
                            if error_logs < self._MAX_ERROR_LOGS:
                                logger.exception(
                                    "Failed to process source record douban_id=%s",
                                    row["douban_id"],
                                )
                                error_logs += 1

                        processed += 1

                        if processed % self._BATCH_SIZE == 0:
                            db.flush()
                            self._set_progress(
                                processed,
                                total,
                                f"Processed {processed} of {total}",
                            )

                    db.flush()

                    # FTS is rebuilt in the same transaction as the metadata
                    # changes. If rebuilding fails, the whole import rolls back.
                    db.execute(text(FTS_REBUILD_SQL))

                # Transaction has committed successfully here.
                logger.info(
                    "Import committed: processed=%s skipped=%s",
                    processed,
                    skipped,
                )

            # Invalidate query caches only after the database commit.
            cache_manager.clear()

            self._set_progress(
                processed,
                total,
                f"Import completed; skipped {skipped} records",
            )
            self._finish(
                "completed",
                f"Import completed; skipped {skipped} records",
            )

        except Exception:
            logger.exception("MovieHub import failed")
            # Avoid exposing filesystem paths or database internals in API status.
            self._finish(
                "failed",
                "Import failed. Check the backend log for details.",
            )

        finally:
            if source_conn is not None:
                source_conn.close()

            self._run_lock.release()

    @staticmethod
    def _validate_source(conn: sqlite3.Connection) -> None:
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

            if cleaned in valid:
                found.add(cleaned)
                continue

            for item in whitelist:
                if item and item in cleaned:
                    found.add(item)

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
                genres.update(self._extract_metadata(value, True))

        for value in (
            detail.get("countries", [])
            + detail.get("regions", [])
            if isinstance(detail.get("countries", []), list)
            and isinstance(detail.get("regions", []), list)
            else []
        ):
            if isinstance(value, str):
                regions.update(self._extract_metadata(value, False))

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
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

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
    ) -> bool:
        """Upsert one movie while preserving data absent from this source."""
        douban_id = self._safe_string(row["douban_id"])
        title = self._safe_string(row["douban_title"])

        if not douban_id or not douban_id.isdigit() or not title:
            return False

        detail = self._extract_detail(row["raw_data"])

        movie = db.scalar(
            select(Movie).where(Movie.douban_id == douban_id)
        )

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
        rating = row["rating"]

        if year is not None:
            movie.year = year

        if rating is not None:
            try:
                movie.rating = float(rating)
            except (TypeError, ValueError):
                pass

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

