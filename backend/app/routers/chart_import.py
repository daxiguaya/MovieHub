
"""API endpoint for importing chart snapshots."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import verify_api_key
from app.limiter import limiter
from app.config import settings
from app.schemas_chart_import import ChartSnapshotImport
from app.services.chart_import_service import (
    ChartImportError,
    chart_import_service,
)

logger = logging.getLogger("moviehub.chart_import.router")

router = APIRouter(
    prefix="/charts",
    tags=["charts"],
)


@router.post(
    "/import",
    dependencies=[Depends(verify_api_key)],
)
@limiter.limit(settings.rate_limit_import)
def import_chart_snapshot(
    request: Request,
    snapshot: ChartSnapshotImport,
    db: Session = Depends(get_db),
):
    """Import or replace one chart snapshot."""
    try:
        result = chart_import_service.import_snapshot(
            db=db,
            snapshot=snapshot,
        )
        return result

    except ChartImportError as exc:
        # ChartImportError contains only safe, user-facing messages.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Unexpected chart import API error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chart import failed. Check the backend log.",
        ) from exc

