
"""Chart query service for MovieHub."""

import base64
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import (
    Chart,
    ChartItem,
    ChartSnapshot,
    Movie,
    MovieGenre,
    MovieRegion,
)
from app.schemas import (
    ChartMovieResponse,
    ChartMoviesListResponse,
    ChartResponse,
    MovieResponse,
)

logger = logging.getLogger("moviehub.charts")

MAX_PAGE_SIZE = 50


class ChartService:
    """Read chart definitions and their dated movie snapshots."""

    @staticmethod
    def _encode_cursor(rank: int) -> str:
        return base64.urlsafe_b64encode(
            str(rank).encode("ascii")
        ).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> int | None:
        if not cursor:
            return None

        try:
            decoded = base64.urlsafe_b64decode(
                cursor.encode("ascii")
            ).decode("ascii")
            rank = int(decoded)
            return rank if rank > 0 else None
        except (ValueError, UnicodeDecodeError):
            return None

    @staticmethod
    def _chart_response(chart: Chart) -> ChartResponse:
        return ChartResponse(
            list_id=chart.list_id,
            slug=chart.slug,
            name=chart.name,
            source=chart.source,
            category=chart.category,
            period=chart.period,
            description=chart.description,
            enabled=bool(chart.enabled),
            display_order=chart.display_order or 0,
            last_updated=chart.last_updated,
        )

    @staticmethod
    def _movie_response(movie: Movie) -> MovieResponse:
        genres = sorted(
            {
                association.genre_obj.name
                for association in movie.genres
                if association.genre_obj is not None
            }
        )
        regions = sorted(
            {
                association.region_obj.name
                for association in movie.regions
                if association.region_obj is not None
            }
        )

        return MovieResponse(
            id=movie.id,
            douban_id=movie.douban_id,
            title=movie.title,
            original_title=movie.original_title,
            year=movie.year,
            rating=movie.rating,
            rating_count=movie.rating_count or 0,
            type=movie.type,
            genres=genres,
            regions=regions,
            updated_at=movie.updated_at,
        )

    def get_charts(
        self,
        db: Session,
        category: str | None = None,
    ) -> list[ChartResponse]:
        """Return enabled charts ordered for display."""
        query = db.query(Chart).filter(Chart.enabled.is_(True))

        if category:
            query = query.filter(Chart.category == category)

        charts = (
            query.order_by(
                Chart.display_order.asc(),
                Chart.list_id.asc(),
            )
            .all()
        )

        return [
            self._chart_response(chart)
            for chart in charts
        ]

    def get_chart(
        self,
        db: Session,
        slug: str,
    ) -> Chart | None:
        """Find one enabled chart by its URL slug."""
        return (
            db.query(Chart)
            .filter(
                Chart.slug == slug,
                Chart.enabled.is_(True),
            )
            .one_or_none()
        )

    def get_chart_movies(
        self,
        db: Session,
        slug: str,
        snapshot_date: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ChartMoviesListResponse | None:
        """Return one dated chart snapshot with cursor pagination."""
        chart = self.get_chart(db, slug)
        if chart is None:
            return None

        snapshot_query = db.query(ChartSnapshot).filter(
            ChartSnapshot.list_id == chart.list_id
        )
        if snapshot_date is None:
            snapshot = (
                snapshot_query
                .order_by(ChartSnapshot.snapshot_date.desc())
                .first()
            )
        else:
            snapshot = snapshot_query.filter(
                ChartSnapshot.snapshot_date == snapshot_date
            ).one_or_none()

        if snapshot is None:
            return ChartMoviesListResponse(
                chart=self._chart_response(chart),
                items=[],
                next_cursor=None,
                total=0,
            )

        query = (
            db.query(ChartItem)
            .join(Movie, Movie.id == ChartItem.movie_id)
            .filter(ChartItem.snapshot_id == snapshot.id)
            .options(
                selectinload(ChartItem.movie).selectinload(
                    Movie.genres
                ).selectinload(MovieGenre.genre_obj),
                selectinload(ChartItem.movie).selectinload(
                    Movie.regions
                ).selectinload(MovieRegion.region_obj),
            )
        )

        total = snapshot.item_count
        cursor_rank = self._decode_cursor(cursor)
        if cursor_rank is not None:
            query = query.filter(ChartItem.rank > cursor_rank)

        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        rows = (
            query.order_by(ChartItem.rank.asc())
            .limit(limit + 1)
            .all()
        )

        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[ChartMovieResponse] = []

        for chart_item in rows:
            movie = chart_item.movie
            if movie is None:
                continue
            movie_data = self._movie_response(movie)
            items.append(
                ChartMovieResponse(
                    **movie_data.model_dump(),
                    rank=chart_item.rank,
                    source_rating=chart_item.source_rating,
                    snapshot_date=snapshot.snapshot_date,
                )
            )

        next_cursor = None
        if has_more and rows:
            next_cursor = self._encode_cursor(rows[-1].rank)

        return ChartMoviesListResponse(
            chart=self._chart_response(chart),
            items=items,
            next_cursor=next_cursor,
            total=total,
        )


chart_service = ChartService()

