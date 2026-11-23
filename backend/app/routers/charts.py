
"""Movie chart API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.schemas import ChartMoviesListResponse, ChartResponse
from app.services.chart_service import chart_service

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
    "/{slug}",
    response_model=ChartMoviesListResponse,
)
@limiter.limit(settings.rate_limit_search)
def get_chart_movies(
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
    result = chart_service.get_chart_movies(
        db=db,
        slug=slug,
        snapshot_date=snapshot_date,
        cursor=cursor,
        limit=limit,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Chart not found",
        )

    return result

