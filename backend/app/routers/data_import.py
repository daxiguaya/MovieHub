"""Protected endpoints for importing an existing Douban Scout database."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies.auth import verify_api_key
from app.limiter import limiter
from app.schemas import ImportStatus
from app.services.import_service import import_service

logger = logging.getLogger("moviehub.data_import.router")
router = APIRouter(prefix="/import", tags=["import"])


class ImportRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=1024)
    force_full: bool = False
    resume_run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


@router.post("", response_model=ImportStatus, dependencies=[Depends(verify_api_key)])
@limiter.limit(settings.rate_limit_import)
def start_import(request: Request, payload: ImportRequest) -> ImportStatus:
    """Start a non-destructive import from an existing Scout SQLite database."""
    import_root = settings.import_dir.expanduser().resolve()
    if not import_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Import directory is not mounted",
        )

    requested = Path(payload.source_path).expanduser()
    source = (requested if requested.is_absolute() else import_root / requested).resolve()
    try:
        source.relative_to(import_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Source database must be inside the configured import directory",
        ) from exc

    if not source.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source database not found")
    try:
        return import_service.start_import(
            str(source),
            force_full=payload.force_full,
            resume_run_id=payload.resume_run_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source database not found") from exc


@router.get("/status", response_model=ImportStatus, dependencies=[Depends(verify_api_key)])
@limiter.limit(settings.rate_limit_import)
def get_import_status(request: Request) -> ImportStatus:
    return import_service.status
