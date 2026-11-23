
"""Movie chart API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.schemas import ChartCompareResponse, ChartMoviesListResponse, ChartResponse, ChartSnapshotResponse
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
    "/{slug}/compare",
    response_model=ChartCompareResponse,
)
@limiter.limit(settings.rate_limit_search)
def compare_chart_snapshots(
    request: Request,
    slug: str,
    from_date: Annotated[
        str,
        Query(pattern=r"^\\d{4}-\\d{2}-\\d{2}$"),
    ],
    to_date: Annotated[
        str,
        Query(pattern=r"^\\d{4}-\\d{2}-\\d{2}$"),
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

