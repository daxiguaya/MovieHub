
"""Movie chart API endpoints."""

import asyncio
import logging
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.schemas import ChartCompareResponse, ChartMoviesListResponse, ChartResponse, ChartSnapshotResponse
from app.services.chart_service import ChartCursorError, chart_service
from app.services.tmdb_client import DETAIL_TTL, tmdb_client

logger = logging.getLogger("moviehub.charts")

TMDB_TITLE_ALIASES = {
    ("movie", "812583"): {"利刃出鞘3", "利刃出鞘3亡者归来", "Wake Up Dead Man: A Knives Out Mystery"},
    ("movie", "1289936"): {"唐顿庄园3", "唐顿庄园盛世终章", "Downton Abbey: The Grand Finale"},
    ("movie", "1088514"): {"隔壁房间", "隔壁的房间", "La habitación de al lado"},
}


def _normalise_title(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in normalized if char.isalnum())


def _extract_tmdb_votes(item, payload: dict) -> tuple[float | None, int] | None:
    """Return TMDB votes only when the response ID and title match the linked movie."""
    try:
        expected_id = int(item.tmdb_id)
    except (TypeError, ValueError):
        return None
    if payload.get("id") != expected_id:
        return None
    keys = ("title", "original_title") if item.type == "movie" else ("name", "original_name")
    provider_titles = {_normalise_title(payload.get(key)) for key in keys}
    provider_titles.discard("")
    stored_titles = {_normalise_title(item.title), _normalise_title(item.original_title)}
    stored_titles.discard("")
    aliases = TMDB_TITLE_ALIASES.get((item.type, str(item.tmdb_id)), set())
    accepted_titles = stored_titles | {_normalise_title(value) for value in aliases}
    if not provider_titles.intersection(accepted_titles):
        return None
    count = payload.get("vote_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return None
    rating = payload.get("vote_average")
    if not isinstance(rating, (int, float)) or isinstance(rating, bool) or not 0 <= rating <= 10:
        rating = None
    return (float(rating) if rating is not None else None, count)


async def _enrich_annual_tmdb_votes(result: ChartMoviesListResponse) -> ChartMoviesListResponse:
    """Attach separately labelled TMDB votes to annual chart cards, without changing Douban fields."""
    if result.chart.category != "annual" or not tmdb_client.token:
        return await _enrich_annual_tmdb_votes(result)
    semaphore = asyncio.Semaphore(4)

    async def enrich(item):
        if not item.tmdb_id or not str(item.tmdb_id).isdigit():
            return item
        async with semaphore:
            try:
                payload = await tmdb_client.get_json(
                    f"/{item.type}/{item.tmdb_id}",
                    {"language": "zh-CN"},
                    DETAIL_TTL,
                )
                votes = _extract_tmdb_votes(item, payload)
                if votes is None:
                    return item
                rating, count = votes
                return item.model_copy(update={"tmdb_rating": rating, "tmdb_rating_count": count})
            except Exception as exc:
                logger.info("Annual TMDB vote lookup unavailable for movie %s: %s", item.id, type(exc).__name__)
                return item

    result.items = await asyncio.gather(*(enrich(item) for item in result.items))
    return result


router = APIRouter(
    prefix="/charts",
    tags=["charts"],
)


@router.get("", response_model=list[ChartResponse])
@limiter.limit(settings.rate_limit_search)
def get_charts(
    request: Request,
    category: Annotated[
        str | None,
        Query(
            description="Optional chart category filter",
            min_length=1,
            max_length=64,
        ),
    ] = None,
    db: Session = Depends(get_db),
) -> list[ChartResponse]:
    """List all enabled charts."""
    return chart_service.get_charts(
        db=db,
        category=category,
    )



@router.get(
    "/{slug}/compare",
    response_model=ChartCompareResponse,
)
@limiter.limit(settings.rate_limit_search)
def compare_chart_snapshots(
    request: Request,
    slug: str,
    from_date: Annotated[
        str,
        Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ],
    to_date: Annotated[
        str,
        Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ],
    db: Session = Depends(get_db),
) -> ChartCompareResponse:
    """Compare rank changes between two existing chart snapshots."""
    if from_date == to_date:
        raise HTTPException(status_code=400, detail="Snapshot dates must be different")
    result = chart_service.compare_snapshots(
        db=db,
        slug=slug,
        from_date=from_date,
        to_date=to_date,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Chart or one of the requested snapshots was not found",
        )
    return result

@router.get(
    "/{slug}/snapshots",
    response_model=list[ChartSnapshotResponse],
)
@limiter.limit(settings.rate_limit_search)
def get_chart_snapshots(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
) -> list[ChartSnapshotResponse]:
    """List available historical dates for one chart."""
    result = chart_service.get_chart_snapshots(db=db, slug=slug)
    if result is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    return result


@router.get(
    "/{slug}",
    response_model=ChartMoviesListResponse,
)
@limiter.limit(settings.rate_limit_search)
async def get_chart_movies(
    request: Request,
    slug: str,
    snapshot_date: Annotated[
        str | None,
        Query(
            description="Snapshot date in YYYY-MM-DD format",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Pagination cursor"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=50),
    ] = 20,
    db: Session = Depends(get_db),
) -> ChartMoviesListResponse:
    """Get the latest or a specified chart snapshot."""
    try:
        result = chart_service.get_chart_movies(
            db=db,
            slug=slug,
            snapshot_date=snapshot_date,
            cursor=cursor,
            limit=limit,
        )
    except ChartCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Chart not found",
        )

    return await _enrich_annual_tmdb_votes(result)

