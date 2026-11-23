
"""Transactional chart snapshot importer for MovieHub."""

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.cache import cache_manager
from app.database import (
    FTS_REBUILD_SQL,
    Chart,
    ChartItem,
    Favorite,
    Genre,
    Movie,
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
        if value is None or value == "":
            return None

        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if result < 0 or result > 10:
            return None

        return result

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None or value == "":
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
        if title:
            movie.title = title

        original_title = ChartImportService._clean_string(
            ChartImportService._value(item, "original_title")
        )
        if original_title:
            movie.original_title = original_title

        year = ChartImportService._safe_int(
            ChartImportService._value(item, "year")
        )
        if year is not None:
            movie.year = year

        rating = ChartImportService._safe_float(
            ChartImportService._value(item, "rating")
        )
        if rating is not None:
            movie.rating = rating

        rating_count = ChartImportService._safe_int(
            ChartImportService._value(item, "rating_count")
        )
        if rating_count is not None and rating_count > 0:
            movie.rating_count = rating_count

        movie_type = ChartImportService._clean_string(
            ChartImportService._value(item, "type")
        )
        if movie_type in ("movie", "tv"):
            movie.type = movie_type

        imdb_id = ChartImportService._clean_string(
            ChartImportService._value(item, "imdb_id")
        )
        if imdb_id:
            movie.imdb_id = imdb_id

        tmdb_id = ChartImportService._clean_string(
            ChartImportService._value(item, "tmdb_id")
        )
        if tmdb_id:
            movie.tmdb_id = tmdb_id

        overview = ChartImportService._clean_string(
            ChartImportService._value(item, "overview")
        )
        if overview:
            movie.overview = overview

        douban_url = ChartImportService._clean_string(
            ChartImportService._value(item, "douban_url")
        )
        if douban_url:
            movie.douban_url = douban_url

        directors = ChartImportService._clean_string_list(
            ChartImportService._value(item, "directors", [])
        )
        if directors:
            movie.directors = ChartImportService._json_list(directors)

        actors = ChartImportService._clean_string_list(
            ChartImportService._value(item, "actors", [])
        )
        if actors:
            movie.actors = ChartImportService._json_list(actors)

        genres = ChartImportService._clean_string_list(
            ChartImportService._value(item, "genres", [])
        )
        if genres:
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
        if regions:
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

            # Validate date before opening the write transaction.
            try:
                datetime.strptime(snapshot_date, "%Y-%m-%d")
            except ValueError as exc:
                raise ChartImportError(
                    "snapshot_date must use YYYY-MM-DD format"
                ) from exc

            if db.in_transaction():
                raise ChartImportError(
                    "The database session already has an active transaction"
                )

            imported_at = datetime.utcnow()

            with db.begin():
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
                        movie_map[douban_id] = movie

                    self._update_movie(
                        db=db,
                        movie=movie,
                        item=item,
                        genre_map=genre_map,
                        region_map=region_map,
                    )

                    db.flush()
                    imported_movie_ids[douban_id] = movie.id

                # Replace only this chart's snapshot on this date.
                # All other dates and all other charts remain untouched.
                db.execute(
                    delete(ChartItem).where(
                        ChartItem.list_id == chart.list_id,
                        ChartItem.snapshot_date == snapshot_date,
                    )
                )

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
                            list_id=chart.list_id,
                            snapshot_date=snapshot_date,
                            douban_id=douban_id,
                            rank=rank,
                            source_rating=source_rating,
                        )
                    )

                db.flush()

                # Keep FTS in sync with the movie records in this transaction.
                db.execute(text(FTS_REBUILD_SQL))

            # Cache invalidation must happen after the transaction commits.
            cache_manager.clear()

            return {
                "success": True,
                "slug": slug,
                "snapshot_date": snapshot_date,
                "imported_count": len(items),
                "message": "Chart snapshot imported successfully",
            }

        except ChartImportError:
            db.rollback()
            raise

        except Exception as exc:
            db.rollback()
            logger.exception("Chart snapshot import failed")
            raise ChartImportError(
                "Chart snapshot import failed. Check the backend log for details."
            ) from exc


chart_import_service = ChartImportService()

