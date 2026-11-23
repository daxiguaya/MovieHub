
"""Movie query and business service for MovieHub."""

import base64
import json
import logging
from typing import Any

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Query, Session, selectinload

from app.cache import cached
from app.database import (
    Genre,
    Movie,
    MovieGenre,
    MoviePoster,
    MovieRegion,
    Region,
)
from app.schemas import (
    GenreCount,
    MovieDetailResponse,
    MovieResponse,
    MoviesListResponse,
    RegionCount,
    StatsResponse,
)

logger = logging.getLogger("moviehub.movies")

MAX_RATING = 10.0
MAX_PAGE_SIZE = 50

SORT_COLUMNS = {
    "rating": Movie.rating,
    "rating_count": Movie.rating_count,
    "year": Movie.year,
}


class MovieService:
    """Movie list, search, filtering and detail operations."""

    @staticmethod
    def _parse_json_list(value: str | None) -> list[str]:
        if not value:
            return []

        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []

        if not isinstance(parsed, list):
            return []

        result: list[str] = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("title")
                    or item.get("name_en")
                )
                if isinstance(name, str) and name.strip():
                    result.append(name.strip())

        return result

    @staticmethod
    def _movie_genres(movie: Movie) -> list[str]:
        return sorted(
            {
                association.genre_obj.name
                for association in movie.genres
                if association.genre_obj is not None
            }
        )

    @staticmethod
    def _movie_regions(movie: Movie) -> list[str]:
        return sorted(
            {
                association.region_obj.name
                for association in movie.regions
                if association.region_obj is not None
            }
        )

    def _to_movie_response(self, movie: Movie) -> MovieResponse:
        return MovieResponse(
            id=movie.id,
            douban_id=movie.douban_id,
            title=movie.title,
            original_title=movie.original_title,
            year=movie.year,
            rating=movie.rating,
            rating_count=movie.rating_count or 0,
            type=movie.type,
            genres=self._movie_genres(movie),
            regions=self._movie_regions(movie),
            updated_at=movie.updated_at,
        )

    def _to_movie_detail_response(
        self,
        movie: Movie,
    ) -> MovieDetailResponse:
        return MovieDetailResponse(
            id=movie.id,
            douban_id=movie.douban_id,
            title=movie.title,
            original_title=movie.original_title,
            year=movie.year,
            rating=movie.rating,
            rating_count=movie.rating_count or 0,
            type=movie.type,
            genres=self._movie_genres(movie),
            regions=self._movie_regions(movie),
            updated_at=movie.updated_at,
            imdb_id=movie.imdb_id,
            tmdb_id=movie.tmdb_id,
            directors=self._parse_json_list(movie.directors),
            actors=self._parse_json_list(movie.actors),
            overview=movie.overview,
            douban_url=movie.douban_url,
            posters=sorted(
                {
                    poster.url
                    for poster in movie.posters
                    if poster.url
                }
            ),
        )

    def get_movie_by_douban_id(
        self,
        db: Session,
        douban_id: str,
    ) -> MovieDetailResponse | None:
        """Get one movie by its stable Douban subject ID."""
        normalized_id = str(douban_id).strip()
        if not normalized_id:
            return None

        movie = (
            db.query(Movie)
            .options(
                selectinload(Movie.genres).selectinload(
                    MovieGenre.genre_obj
                ),
                selectinload(Movie.regions).selectinload(
                    MovieRegion.region_obj
                ),
                selectinload(Movie.posters),
            )
            .filter(Movie.douban_id == normalized_id)
            .one_or_none()
        )

        if movie is None:
            return None

        return self._to_movie_detail_response(movie)

    def get_movie_by_internal_id(
        self,
        db: Session,
        movie_id: int,
    ) -> MovieDetailResponse | None:
        """Get one movie by the legacy internal integer ID."""
        movie = (
            db.query(Movie)
            .options(
                selectinload(Movie.genres).selectinload(
                    MovieGenre.genre_obj
                ),
                selectinload(Movie.regions).selectinload(
                    MovieRegion.region_obj
                ),
                selectinload(Movie.posters),
            )
            .filter(Movie.id == movie_id)
            .one_or_none()
        )

        if movie is None:
            return None

        return self._to_movie_detail_response(movie)

    def get_movies(
        self,
        db: Session,
        cursor: str | None = None,
        limit: int = 20,
        type: str | None = None,
        min_rating: float | None = None,
        max_rating: float | None = None,
        min_rating_count: int | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
        genres: list[str] | None = None,
        exclude_genres: list[str] | None = None,
        regions: list[str] | None = None,
        search: str | None = None,
        sort_by: str = "rating_count",
        sort_order: str = "desc",
    ) -> MoviesListResponse:
        """Return a filtered and cursor-paginated movie list."""
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))

        if sort_by not in SORT_COLUMNS:
            sort_by = "rating_count"

        if sort_order not in {"asc", "desc"}:
            sort_order = "desc"

        query = self._apply_filters(
            db=db,
            type=type,
            min_rating=min_rating,
            max_rating=max_rating,
            min_rating_count=min_rating_count,
            min_year=min_year,
            max_year=max_year,
            genres=genres,
            exclude_genres=exclude_genres,
            regions=regions,
            search=search,
        )

        total = self._get_filtered_count(
            db=db,
            type=type,
            min_rating=min_rating,
            max_rating=max_rating,
            min_rating_count=min_rating_count,
            min_year=min_year,
            max_year=max_year,
            genres=genres,
            exclude_genres=exclude_genres,
            regions=regions,
            search=search,
        )

        query = query.options(
            selectinload(Movie.genres).selectinload(
                MovieGenre.genre_obj
            ),
            selectinload(Movie.regions).selectinload(
                MovieRegion.region_obj
            ),
        )

        sort_column = SORT_COLUMNS[sort_by]

        cursor_data = self._decode_cursor(cursor)
        if cursor_data is not None:
            query = self._apply_cursor(
                query,
                sort_column,
                sort_order,
                cursor_data,
            )

        if sort_order == "desc":
            query = query.order_by(
                sort_column.desc(),
                Movie.id.desc(),
            )
        else:
            query = query.order_by(
                sort_column.asc(),
                Movie.id.asc(),
            )

        rows = query.limit(limit + 1).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        items = [
            self._to_movie_response(movie)
            for movie in rows
        ]

        next_cursor = None
        if has_more and rows:
            last_movie = rows[-1]
            next_cursor = self._encode_cursor(
                {
                    "value": getattr(last_movie, sort_by),
                    "id": last_movie.id,
                }
            )

        return MoviesListResponse(
            items=items,
            next_cursor=next_cursor,
            total=total,
        )

    @staticmethod
    def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
        if not cursor:
            return None

        try:
            decoded = base64.urlsafe_b64decode(
                cursor.encode("ascii")
            ).decode("utf-8")
            data = json.loads(decoded)

            if not isinstance(data, dict):
                return None

            # Cursors are opaque client input. Accept only the exact
            # scalar shape emitted by _encode_cursor for the numeric sort
            # columns; malformed JSON must fall back to the first page
            # rather than reaching SQLAlchemy/SQLite as a bind error.
            if set(data) != {"id", "value"}:
                return None

            cursor_id = data["id"]
            if (
                isinstance(cursor_id, bool)
                or not isinstance(cursor_id, int)
                or cursor_id <= 0
                or cursor_id > 9_223_372_036_854_775_807
            ):
                return None

            cursor_value = data["value"]
            if cursor_value is not None:
                if isinstance(cursor_value, bool) or not isinstance(
                    cursor_value, (int, float)
                ):
                    return None
                try:
                    if not math.isfinite(cursor_value):
                        return None
                except (OverflowError, TypeError, ValueError):
                    return None
                if isinstance(cursor_value, int) and abs(cursor_value) > 9_223_372_036_854_775_807:
                    return None

            return {"id": cursor_id, "value": cursor_value}

        except (
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return None

    @staticmethod
    def _encode_cursor(data: dict[str, Any]) -> str:
        raw = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        return base64.urlsafe_b64encode(raw).decode("ascii")

    @staticmethod
    def _apply_cursor(
        query: Query,
        sort_column: Any,
        sort_order: str,
        cursor_data: dict[str, Any],
    ) -> Query:
        """Apply a stable keyset cursor for the selected sort column."""
        cursor_id = cursor_data.get("id")
        cursor_value = cursor_data.get("value")

        try:
            cursor_id = int(cursor_id)
        except (TypeError, ValueError):
            return query

        if sort_order == "desc":
            if cursor_value is None:
                return query.filter(
                    sort_column.is_(None),
                    Movie.id < cursor_id,
                )

            return query.filter(
                or_(
                    sort_column < cursor_value,
                    and_(sort_column == cursor_value, Movie.id < cursor_id),
                    sort_column.is_(None),
                )
            )

        if cursor_value is None:
            return query.filter(
                sort_column.is_(None),
                Movie.id > cursor_id,
            )

        return query.filter(
            or_(
                sort_column > cursor_value,
                and_(sort_column == cursor_value, Movie.id > cursor_id),
            )
        )

    def _apply_filters(
        self,
        db: Session,
        type: str | None = None,
        min_rating: float | None = None,
        max_rating: float | None = None,
        min_rating_count: int | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
        genres: list[str] | None = None,
        exclude_genres: list[str] | None = None,
        regions: list[str] | None = None,
        search: str | None = None,
    ) -> Query:
        query = db.query(Movie)

        if search:
            query = self._apply_search(db, query, search)

        if type:
            query = query.filter(Movie.type == type)

        if min_rating_count is not None:
            query = query.filter(
                Movie.rating_count >= min_rating_count
            )

        query = self._apply_rating_range(
            query,
            min_rating,
            max_rating,
        )

        query = self._apply_year_range(
            query,
            min_year,
            max_year,
        )

        query = self._apply_genre_and_region_filters(
            db,
            query,
            genres,
            exclude_genres,
            regions,
        )

        return query

    @staticmethod
    def _apply_search(
        db: Session,
        query: Query,
        search: str,
    ) -> Query:
        """Search movie titles directly without requiring FTS5."""
        terms = [
            term.strip()
            for term in search.split()
            if term.strip()
        ]

        if not terms:
            return query

        # Every term must match either the Chinese/display title or
        # the original title. SQLAlchemy escapes LIKE wildcards.
        conditions = []

        for term in terms:
            conditions.append(
                or_(
                    Movie.title.contains(term, autoescape=True),
                    Movie.original_title.contains(
                        term,
                        autoescape=True,
                    ),
                )
            )

        return query.filter(and_(*conditions))

    @staticmethod
    def _apply_rating_range(
        query: Query,
        min_rating: float | None,
        max_rating: float | None,
    ) -> Query:
        effective_min = (
            min_rating if min_rating is not None else 0
        )
        effective_max = (
            max_rating if max_rating is not None else MAX_RATING
        )

        if effective_min > 0:
            query = query.filter(
                Movie.rating.isnot(None),
                Movie.rating.between(
                    effective_min,
                    effective_max,
                ),
            )

        elif effective_max < MAX_RATING:
            query = query.filter(
                (
                    Movie.rating.between(0, effective_max)
                )
                | Movie.rating.is_(None)
            )

        return query

    @staticmethod
    def _apply_year_range(
        query: Query,
        min_year: int | None,
        max_year: int | None,
    ) -> Query:
        if min_year is not None and max_year is not None:
            return query.filter(
                Movie.year.between(min_year, max_year)
            )

        if min_year is not None:
            return query.filter(Movie.year >= min_year)

        if max_year is not None:
            return query.filter(
                (Movie.year <= max_year)
                | Movie.year.is_(None)
            )

        return query

    @staticmethod
    def _apply_genre_and_region_filters(
        db: Session,
        query: Query,
        genres: list[str] | None,
        exclude_genres: list[str] | None,
        regions: list[str] | None,
    ) -> Query:
        if genres:
            genre_subquery = (
                db.query(MovieGenre.movie_id)
                .join(Genre, Genre.id == MovieGenre.genre_id)
                .filter(Genre.name.in_(genres))
                .group_by(MovieGenre.movie_id)
                .having(func.count(func.distinct(Genre.name)) == len(set(genres)))
            )

            query = query.filter(Movie.id.in_(genre_subquery))

        if regions:
            region_subquery = (
                db.query(MovieRegion.movie_id)
                .join(Region, Region.id == MovieRegion.region_id)
                .filter(Region.name.in_(regions))
                .distinct()
            )

            query = query.filter(Movie.id.in_(region_subquery))

        if exclude_genres:
            excluded = (
                db.query(MovieGenre.movie_id)
                .join(Genre, Genre.id == MovieGenre.genre_id)
                .filter(Genre.name.in_(exclude_genres))
                .distinct()
            )

            query = query.filter(~Movie.id.in_(excluded))

        return query

    @cached(prefix="genres")
    def get_genres(
        self,
        db: Session,
        type: str | None = None,
    ) -> list[GenreCount]:
        query = (
            db.query(
                Genre.name,
                func.count(func.distinct(MovieGenre.movie_id)).label("count"),
            )
            .join(
                MovieGenre,
                MovieGenre.genre_id == Genre.id,
            )
            .join(
                Movie,
                Movie.id == MovieGenre.movie_id,
            )
        )

        if type:
            query = query.filter(Movie.type == type)

        results = (
            query.group_by(Genre.name)
            .order_by(
                func.count(func.distinct(MovieGenre.movie_id)).desc(),
                Genre.name.asc(),
            )
            .all()
        )

        return [
            GenreCount(genre=row[0], count=row[1])
            for row in results
        ]

    @cached(prefix="regions")
    def get_regions(
        self,
        db: Session,
        type: str | None = None,
    ) -> list[RegionCount]:
        query = (
            db.query(
                Region.name,
                func.count(func.distinct(MovieRegion.movie_id)).label("count"),
            )
            .join(
                MovieRegion,
                MovieRegion.region_id == Region.id,
            )
            .join(
                Movie,
                Movie.id == MovieRegion.movie_id,
            )
        )

        if type:
            query = query.filter(Movie.type == type)

        results = (
            query.group_by(Region.name)
            .order_by(
                func.count(func.distinct(MovieRegion.movie_id)).desc(),
                Region.name.asc(),
            )
            .all()
        )

        return [
            RegionCount(region=row[0], count=row[1])
            for row in results
        ]

    @cached(prefix="stats")
    def get_stats(self, db: Session) -> StatsResponse:
        total_movies = (
            db.query(Movie)
            .filter(Movie.type == "movie")
            .count()
        )

        total_tv = (
            db.query(Movie)
            .filter(Movie.type == "tv")
            .count()
        )

        average = (
            db.query(func.avg(Movie.rating))
            .scalar()
            or 0.0
        )

        return StatsResponse(
            total_movies=total_movies,
            total_tv=total_tv,
            avg_rating=round(float(average), 2),
            total_genres=db.query(Genre).count(),
            total_regions=db.query(Region).count(),
        )

    @cached(prefix="movie_count")
    def _get_filtered_count(
        self,
        db: Session,
        type: str | None = None,
        min_rating: float | None = None,
        max_rating: float | None = None,
        min_rating_count: int | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
        genres: list[str] | None = None,
        exclude_genres: list[str] | None = None,
        regions: list[str] | None = None,
        search: str | None = None,
    ) -> int:
        query = self._apply_filters(
            db=db,
            type=type,
            min_rating=min_rating,
            max_rating=max_rating,
            min_rating_count=min_rating_count,
            min_year=min_year,
            max_year=max_year,
            genres=genres,
            exclude_genres=exclude_genres,
            regions=regions,
            search=search,
        )

        return query.order_by(None).count()


movie_service = MovieService()

