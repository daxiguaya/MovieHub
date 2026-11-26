
"""Transactional chart snapshot importer for MovieHub."""

import hashlib
import json
import logging
import math
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.cache import cache_manager
from app.chart_definitions import get_chart_definition
from app.database import (
    Chart,
    ChartItem,
    ChartSnapshot,
    Favorite,
    Genre,
    Movie,
    MovieMetadataProvenance,
    MovieGenre,
    MoviePoster,
    MovieRegion,
    Region,
)
from app.metadata_constants import VALID_GENRES, VALID_REGIONS
from app.schemas_chart_import import ChartSnapshotImport

logger = logging.getLogger("moviehub.chart_import")


class ChartImportError(Exception):
    """Safe, user-facing chart import error."""


class ChartImportService:
    """Import one chart snapshot without damaging other snapshots."""

    @staticmethod
    def _value(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @staticmethod
    def _clean_string(value: Any) -> str | None:
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    @staticmethod
    def _clean_string_list(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []

        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("name") or item.get("title")

            cleaned = ChartImportService._clean_string(item)
            if cleaned and cleaned not in result:
                result.append(cleaned)

        return result

    @staticmethod
    def _json_list(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None or value == "" or isinstance(value, bool):
            return None

        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if not math.isfinite(result) or result < 0 or result > 10:
            return None

        return result

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        # bool is an int subclass in Python, but it is never a valid
        # year/rating count/rank in an imported catalogue.
        if value is None or value == "" or isinstance(value, bool):
            return None
        if isinstance(value, float) and not value.is_integer():
            return None

        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _ensure_metadata(
        db: Session,
        model: type,
        names: set[str],
        allowed_names: set[str],
    ) -> dict[str, int]:
        """Create missing bounded metadata rows and return name -> id.

        allowed_names remains in the signature for compatibility with callers;
        the seed vocabulary is not an exhaustive taxonomy and must not discard
        legitimate new genres or production regions.
        """
        names = {
            name.strip()
            for name in names
            if isinstance(name, str)
            and name.strip()
            and len(name.strip()) <= 32
            and not any(ord(char) < 32 for char in name)
        }

        existing_rows = db.scalars(
            select(model).where(model.name.in_(names))
        ).all() if names else []

        result = {item.name: item.id for item in existing_rows}

        missing = names - result.keys()
        for name in sorted(missing):
            db.add(model(name=name))

        if missing:
            db.flush()

            rows = db.scalars(
                select(model).where(model.name.in_(missing))
            ).all()

            result.update({item.name: item.id for item in rows})

        return result

    @staticmethod
    def _record_metadata_provenance(
        db: Session,
        movie: Movie,
        field_name: str,
        value: Any,
        source: str,
        source_url: str,
        observed_at: datetime,
    ) -> None:
        """Record a source observation without duplicating the metadata value."""
        if value is None or value == "" or value == "[]":
            return
        serialized = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if isinstance(value, (list, dict))
            else str(value)
        )
        value_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = db.scalar(
            select(MovieMetadataProvenance.id).where(
                MovieMetadataProvenance.movie_id == movie.id,
                MovieMetadataProvenance.field_name == field_name,
                MovieMetadataProvenance.source == source,
                MovieMetadataProvenance.source_url == source_url,
                MovieMetadataProvenance.value_sha256 == value_sha256,
            )
        )
        if existing is None:
            db.add(
                MovieMetadataProvenance(
                    movie_id=movie.id,
                    field_name=field_name,
                    source=source,
                    source_url=source_url,
                    observed_at=observed_at,
                    value_sha256=value_sha256,
                )
            )

    @staticmethod
    def _update_movie(
        db: Session,
        movie: Movie,
        item: Any,
        genre_map: dict[str, int],
        region_map: dict[str, int],
    ) -> None:
        """Update a movie while preserving fields absent from the import."""
        title = ChartImportService._clean_string(
            ChartImportService._value(item, "title")
        )
        if title and not (movie.title or '').strip():
            movie.title = title

        original_title = ChartImportService._clean_string(
            ChartImportService._value(item, "original_title")
        )
        if original_title and not movie.original_title:
            movie.original_title = original_title

        year = ChartImportService._safe_int(
            ChartImportService._value(item, "year")
        )
        # Match the public import schema even when internal callers pass raw
        # mappings and bypass Pydantic validation.
        if year is not None and 1870 <= year <= 2200 and movie.year is None:
            movie.year = year

        rating = ChartImportService._safe_float(
            ChartImportService._value(item, "rating")
        )
        if rating is not None and movie.rating is None:
            movie.rating = rating

        rating_count = ChartImportService._safe_int(
            ChartImportService._value(item, "rating_count")
        )
        if rating_count is not None and rating_count > 0 and not movie.rating_count:
            movie.rating_count = rating_count

        movie_type = ChartImportService._clean_string(
            ChartImportService._value(item, "type")
        )
        if movie_type in ("movie", "tv") and not movie.type:
            movie.type = movie_type

        imdb_id = ChartImportService._clean_string(
            ChartImportService._value(item, "imdb_id")
        )
        if (
            imdb_id
            and re.fullmatch(r"tt[0-9]{7,12}", imdb_id)
            and not movie.imdb_id
        ):
            movie.imdb_id = imdb_id

        tmdb_id = ChartImportService._clean_string(
            ChartImportService._value(item, "tmdb_id")
        )
        if tmdb_id and not movie.tmdb_id:
            movie.tmdb_id = tmdb_id

        overview = ChartImportService._clean_string(
            ChartImportService._value(item, "overview")
        )
        if overview and not movie.overview:
            movie.overview = overview

        douban_url = ChartImportService._clean_string(
            ChartImportService._value(item, "douban_url")
        )
        if douban_url and not movie.douban_url:
            movie.douban_url = douban_url

        directors = ChartImportService._clean_string_list(
            ChartImportService._value(item, "directors", [])
        )
        if directors and movie.directors in (None, '', '[]'):
            movie.directors = ChartImportService._json_list(directors)

        actors = ChartImportService._clean_string_list(
            ChartImportService._value(item, "actors", [])
        )
        if actors and movie.actors in (None, '', '[]'):
            movie.actors = ChartImportService._json_list(actors)

        genres = ChartImportService._clean_string_list(
            ChartImportService._value(item, "genres", [])
        )
        if genres and not movie.genres:
            genre_ids = {
                genre_map[name]
                for name in genres
                if name in genre_map
            }

            if genre_ids:
                db.execute(
                    delete(MovieGenre).where(
                        MovieGenre.movie_id == movie.id
                    )
                )

                for genre_id in genre_ids:
                    db.add(
                        MovieGenre(
                            movie_id=movie.id,
                            genre_id=genre_id,
                        )
                    )

        regions = ChartImportService._clean_string_list(
            ChartImportService._value(item, "regions", [])
        )
        if regions and not movie.regions:
            region_ids = {
                region_map[name]
                for name in regions
                if name in region_map
            }

            if region_ids:
                db.execute(
                    delete(MovieRegion).where(
                        MovieRegion.movie_id == movie.id
                    )
                )

                for region_id in region_ids:
                    db.add(
                        MovieRegion(
                            movie_id=movie.id,
                            region_id=region_id,
                        )
                    )

        # Poster URLs are additive. A chart import must not remove
        # posters supplied by the original Scout import or another source.
        posters = ChartImportService._clean_string_list(
            ChartImportService._value(item, "posters", [])
        )

        if posters:
            existing = set(
                db.scalars(
                    select(MoviePoster.url).where(
                        MoviePoster.movie_id == movie.id
                    )
                ).all()
            )

            for url in posters:
                if url not in existing:
                    db.add(
                        MoviePoster(
                            movie_id=movie.id,
                            url=url,
                        )
                    )

    def import_snapshot(
        self,
        db: Session,
        snapshot: ChartSnapshotImport,
        *,
        _nested_transaction: bool = False,
        _clear_cache: bool = True,
    ) -> dict[str, Any]:
        """Import or replace one chart's snapshot for one date.

        The caller should supply a fresh SQLAlchemy Session with no active
        transaction. This method owns the transaction and commits it.
        """
        try:
            slug = self._clean_string(
                self._value(snapshot, "slug")
            )
            name = self._clean_string(
                self._value(snapshot, "name")
            )
            source = self._clean_string(
                self._value(snapshot, "source")
            )
            category = self._clean_string(
                self._value(snapshot, "category")
            )
            snapshot_date = self._clean_string(
                self._value(snapshot, "snapshot_date")
            )
            items = self._value(snapshot, "movies", [])

            if not all((slug, name, source, category, snapshot_date)):
                raise ChartImportError(
                    "Required chart information is missing"
                )

            if not items:
                raise ChartImportError(
                    "The snapshot contains no movies; existing data was not changed"
                )

            # Enforce required poster coverage even for internal callers that
            # bypass the Pydantic import schema with raw mappings.
            definition = get_chart_definition(slug)
            if definition is not None and definition.require_posters:
                missing_posters = [
                    self._clean_string(self._value(item, "douban_id")) or "unknown"
                    for item in items
                    if not self._clean_string_list(
                        self._value(item, "posters", [])
                    )
                ]
                if missing_posters:
                    preview = ", ".join(missing_posters[:10])
                    raise ChartImportError(
                        f"Chart {slug} requires at least one poster per movie; "
                        f"missing for Douban IDs: {preview}"
                    )

            # Validate date before opening the write transaction.
            try:
                datetime.strptime(snapshot_date, "%Y-%m-%d")
            except ValueError as exc:
                raise ChartImportError(
                    "snapshot_date must use YYYY-MM-DD format"
                ) from exc

            # Validate rank shape and uniqueness before opening the write
            # transaction. The Pydantic schema normally guarantees this, but
            # the service also accepts mapping-like inputs from internal tools.
            ranks: list[int] = []
            for item in items:
                douban_id = self._clean_string(
                    self._value(item, "douban_id")
                )
                rank = self._safe_int(self._value(item, "rank"))
                if rank is None or rank < 1:
                    raise ChartImportError(
                        f"Movie {douban_id} has an invalid rank"
                    )
                ranks.append(rank)

            if len(ranks) != len(set(ranks)):
                raise ChartImportError(
                    "The snapshot contains duplicate ranks"
                )

            if db.in_transaction() and not _nested_transaction:
                raise ChartImportError(
                    "The database session already has an active transaction"
                )

            imported_at = datetime.utcnow()
            transaction = db.begin_nested() if _nested_transaction else db.begin()

            with transaction:
                chart = db.scalar(
                    select(Chart).where(Chart.slug == slug)
                )

                if chart is None:
                    chart = Chart(
                        slug=slug,
                        name=name,
                        source=source,
                        category=category,
                        period=self._clean_string(
                            self._value(snapshot, "period")
                        ),
                        description=self._clean_string(
                            self._value(snapshot, "description")
                        ),
                        enabled=True,
                        display_order=0,
                    )
                    db.add(chart)
                    db.flush()
                else:
                    chart.name = name
                    chart.source = source
                    chart.category = category

                    period = self._clean_string(
                        self._value(snapshot, "period")
                    )
                    description = self._clean_string(
                        self._value(snapshot, "description")
                    )

                    if period:
                        chart.period = period

                    if description:
                        chart.description = description

                # Preserve the enabled flag and display order of existing charts.
                chart.last_updated = imported_at
                chart.updated_at = imported_at

                all_genres: set[str] = set()
                all_regions: set[str] = set()
                douban_ids: list[str] = []

                for item in items:
                    douban_id = self._clean_string(
                        self._value(item, "douban_id")
                    )

                    if not douban_id or not douban_id.isdigit():
                        raise ChartImportError(
                            "A snapshot item has an invalid Douban ID"
                        )

                    douban_ids.append(douban_id)

                    all_genres.update(
                        self._clean_string_list(
                            self._value(item, "genres", [])
                        )
                    )
                    all_regions.update(
                        self._clean_string_list(
                            self._value(item, "regions", [])
                        )
                    )

                if len(douban_ids) != len(set(douban_ids)):
                    raise ChartImportError(
                        "The snapshot contains duplicate Douban IDs"
                    )

                genre_map = self._ensure_metadata(
                    db,
                    Genre,
                    all_genres,
                    set(VALID_GENRES),
                )
                region_map = self._ensure_metadata(
                    db,
                    Region,
                    all_regions,
                    set(VALID_REGIONS),
                )

                # Fetch existing movies in one query, keyed by the external ID.
                existing_movies = db.scalars(
                    select(Movie).where(
                        Movie.douban_id.in_(douban_ids)
                    )
                ).all()

                movie_map = {
                    movie.douban_id: movie
                    for movie in existing_movies
                }

                # A chart must never silently point at a movie record whose
                # stored media type contradicts the snapshot. Do not rewrite
                # Scout-owned movie identity/type from chart data.
                for item in items:
                    douban_id = self._clean_string(
                        self._value(item, "douban_id")
                    )
                    item_type = self._clean_string(
                        self._value(item, "type")
                    ) or "movie"
                    if item_type not in ("movie", "tv"):
                        raise ChartImportError(
                            f"Movie {douban_id} has an invalid media type"
                        )

                    existing_movie = movie_map.get(douban_id)
                    if (
                        existing_movie is not None
                        and existing_movie.type != item_type
                    ):
                        raise ChartImportError(
                            f"Movie {douban_id} media type mismatch: "
                            f"MovieHub has {existing_movie.type!r}, "
                            f"snapshot has {item_type!r}; snapshot was not imported"
                        )

                imported_movie_ids: dict[str, int] = {}

                for item in items:
                    douban_id = self._clean_string(
                        self._value(item, "douban_id")
                    )

                    movie = movie_map.get(douban_id)

                    if movie is None:
                        title = self._clean_string(
                            self._value(item, "title")
                        )
                        if not title:
                            raise ChartImportError(
                                f"Movie {douban_id} has no title"
                            )

                        movie_type = self._clean_string(
                            self._value(item, "type")
                        ) or "movie"

                        if movie_type not in ("movie", "tv"):
                            movie_type = "movie"

                        movie = Movie(
                            douban_id=douban_id,
                            title=title,
                            type=movie_type,
                            rating_count=0,
                        )
                        db.add(movie)
                        # Metadata associations use the generated movie primary key.
                        # Flush the parent row before creating MovieGenre/MovieRegion.
                        db.flush()
                        movie_map[douban_id] = movie

                    tracked_fields = (
                        "original_title", "year", "rating", "rating_count",
                        "directors", "actors", "overview",
                    )
                    before = {field: getattr(movie, field) for field in tracked_fields}
                    self._update_movie(
                        db=db,
                        movie=movie,
                        item=item,
                        genre_map=genre_map,
                        region_map=region_map,
                    )
                    source_url = self._clean_string(
                        self._value(item, "douban_url")
                    ) or ""
                    for field in tracked_fields:
                        previous = before[field]
                        current = getattr(movie, field)
                        was_empty = previous in (None, "", "[]", 0)
                        if was_empty and current not in (None, "", "[]", 0):
                            self._record_metadata_provenance(
                                db=db,
                                movie=movie,
                                field_name=field,
                                value=current,
                                source=source,
                                source_url=source_url,
                                observed_at=imported_at,
                            )

                    db.flush()
                    imported_movie_ids[douban_id] = movie.id

                # Replace only this chart/date snapshot. Its items cascade;
                # all other dates and all other charts remain untouched.
                previous_snapshot = db.scalar(
                    select(ChartSnapshot).where(
                        ChartSnapshot.list_id == chart.list_id,
                        ChartSnapshot.snapshot_date == snapshot_date,
                    )
                )
                if previous_snapshot is not None:
                    db.delete(previous_snapshot)
                    db.flush()

                chart_snapshot = ChartSnapshot(
                    list_id=chart.list_id,
                    snapshot_date=snapshot_date,
                    imported_at=imported_at,
                    item_count=len(items),
                )
                db.add(chart_snapshot)
                db.flush()

                for item in items:
                    douban_id = self._clean_string(
                        self._value(item, "douban_id")
                    )
                    rank = self._safe_int(
                        self._value(item, "rank")
                    )

                    if rank is None or rank < 1:
                        raise ChartImportError(
                            f"Movie {douban_id} has an invalid rank"
                        )

                    source_rating = self._safe_float(
                        self._value(item, "source_rating")
                    )

                    db.add(
                        ChartItem(
                            snapshot_id=chart_snapshot.id,
                            movie_id=imported_movie_ids[douban_id],
                            rank=rank,
                            source_rating=source_rating,
                        )
                    )

                db.flush()


            # In batch mode, the outer transaction owns the commit and cache
            # invalidation. Never clear caches for an uncommitted savepoint.
            if _clear_cache:
                cache_manager.clear()

            return {
                "success": True,
                "slug": slug,
                "snapshot_date": snapshot_date,
                "imported_count": len(items),
                "message": "Chart snapshot imported successfully",
            }

        except ChartImportError:
            if not _nested_transaction:
                db.rollback()
            raise

        except Exception as exc:
            if not _nested_transaction:
                db.rollback()
            logger.exception("Chart snapshot import failed")
            raise ChartImportError(
                "Chart snapshot import failed. Check the backend log for details."
            ) from exc


    def import_snapshots(
        self,
        db: Session,
        snapshots: list[ChartSnapshotImport],
    ) -> dict[str, Any]:
        """Import multiple chart snapshots as one all-or-nothing transaction."""
        if not snapshots:
            raise ChartImportError("No chart snapshots were supplied")
        if db.in_transaction():
            raise ChartImportError(
                "The database session already has an active transaction"
            )

        keys: list[tuple[str, str]] = []
        for snapshot in snapshots:
            slug = self._clean_string(self._value(snapshot, "slug"))
            snapshot_date = self._clean_string(
                self._value(snapshot, "snapshot_date")
            )
            if not slug or not snapshot_date:
                raise ChartImportError(
                    "Every batch snapshot must include a chart slug and date"
                )
            keys.append((slug, snapshot_date))

        if len(keys) != len(set(keys)):
            raise ChartImportError(
                "The batch contains duplicate chart/date snapshots"
            )

        results: list[dict[str, Any]] = []
        try:
            with db.begin():
                # sqlite3 legacy transaction mode does not BEGIN for a SAVEPOINT.
                # Force a real outer transaction before the first nested savepoint,
                # otherwise releasing that savepoint can commit independently.
                db.connection().exec_driver_sql("BEGIN")
                for snapshot in snapshots:
                    results.append(
                        self.import_snapshot(
                            db,
                            snapshot,
                            _nested_transaction=True,
                            _clear_cache=False,
                        )
                    )
            # Invalidate once, and only after the entire batch is committed.
            cache_manager.clear()
        except ChartImportError:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Chart snapshot batch import failed")
            raise ChartImportError(
                "Chart snapshot batch import failed; no snapshots were committed"
            ) from exc

        return {
            "success": True,
            "imported_count": len(results),
            "snapshots": results,
            "message": "All chart snapshots imported successfully",
        }


chart_import_service = ChartImportService()

