
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
    ChartSnapshotResponse,
    MovieResponse,
)

logger = logging.getLogger("moviehub.charts")

MAX_PAGE_SIZE = 50


class ChartCursorError(ValueError):
    """Raised when a chart pagination cursor is malformed."""


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
            decoded_bytes = base64.b64decode(
                cursor.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            decoded = decoded_bytes.decode("ascii")
            rank = int(decoded)
            if rank <= 0 or str(rank) != decoded:
                raise ValueError("cursor rank is not canonical")
            return rank
        except (ValueError, UnicodeEncodeError, UnicodeDecodeError) as exc:
            raise ChartCursorError("Invalid chart pagination cursor") from exc

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

    def get_chart_snapshots(
        self,
        db: Session,
        slug: str,
    ) -> list[ChartSnapshotResponse] | None:
        """List available historical snapshots for an enabled chart."""
        chart = self.get_chart(db, slug)
        if chart is None:
            return None

        snapshots = (
            db.query(ChartSnapshot)
            .filter(ChartSnapshot.list_id == chart.list_id)
            .order_by(ChartSnapshot.snapshot_date.desc())
            .all()
        )
        return [
            ChartSnapshotResponse(
                snapshot_date=item.snapshot_date,
                imported_at=item.imported_at,
                item_count=item.item_count,
            )
            for item in snapshots
        ]

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


    def compare_snapshots(
        self,
        db: Session,
        slug: str,
        from_date: str,
        to_date: str,
    ):
        """Compare two dated snapshots using MovieHub's internal movie IDs."""
        from app.schemas import ChartCompareResponse, ChartRankChange

        chart = self.get_chart(db, slug)
        if chart is None:
            return None

        snapshots = (
            db.query(ChartSnapshot)
            .filter(
                ChartSnapshot.list_id == chart.list_id,
                ChartSnapshot.snapshot_date.in_([from_date, to_date]),
            )
            .all()
        )
        by_date = {snapshot.snapshot_date: snapshot for snapshot in snapshots}
        before_snapshot = by_date.get(from_date)
        after_snapshot = by_date.get(to_date)
        if before_snapshot is None or after_snapshot is None:
            return None

        def ranked_items(snapshot_id: int) -> dict[int, tuple[int, Movie]]:
            rows = (
                db.query(ChartItem, Movie)
                .join(Movie, Movie.id == ChartItem.movie_id)
                .filter(ChartItem.snapshot_id == snapshot_id)
                .all()
            )
            return {
                movie.id: (chart_item.rank, movie)
                for chart_item, movie in rows
            }

        before = ranked_items(before_snapshot.id)
        after = ranked_items(after_snapshot.id)
        changes = []
        for movie_id in before.keys() | after.keys():
            before_entry = before.get(movie_id)
            after_entry = after.get(movie_id)
            movie = (after_entry or before_entry)[1]
            before_rank = before_entry[0] if before_entry else None
            after_rank = after_entry[0] if after_entry else None

            if before_rank is None:
                state = "new"
            elif after_rank is None:
                state = "removed"
            elif before_rank == after_rank:
                state = "unchanged"
            else:
                state = "moved"

            changes.append(
                ChartRankChange(
                    movie_id=movie.id,
                    douban_id=movie.douban_id,
                    title=movie.title,
                    year=movie.year,
                    type=movie.type,
                    before_rank=before_rank,
                    after_rank=after_rank,
                    rank_change=(
                        before_rank - after_rank
                        if before_rank is not None and after_rank is not None
                        else None
                    ),
                    status=state,
                )
            )

        changes.sort(
            key=lambda item: (
                item.after_rank is None,
                item.after_rank if item.after_rank is not None else item.before_rank or 0,
                item.title.casefold(),
            )
        )
        return ChartCompareResponse(
            chart=self._chart_response(chart),
            from_date=from_date,
            to_date=to_date,
            total_before=len(before),
            total_after=len(after),
            items=changes,
        )



chart_service = ChartService()

