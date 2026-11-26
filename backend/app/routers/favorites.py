"""Single-user favorites API, keyed by MovieHub's internal movie ID."""

import asyncio
import json
import logging
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import Favorite, Movie, MovieGenre, MovieRegion, get_db
from app.dependencies.auth import verify_api_key
from app.limiter import limiter
from app.schemas import FavoriteResponse, FavoriteUpsert, MovieResponse
from app.services.imdb_rating_index import lookup_ratings
from app.services.provider_cache import provider_response_cache
from app.services.tmdb_client import DETAIL_TTL, tmdb_client

logger = logging.getLogger("moviehub.favorites")


router = APIRouter(
    prefix="/favorites",
    tags=["favorites"],
    dependencies=[Depends(verify_api_key)],
)


def _response(favorite: Favorite) -> FavoriteResponse:
    movie = favorite.movie
    movie_response = MovieResponse(
        id=movie.id,
        douban_id=movie.douban_id,
        tmdb_id=movie.tmdb_id,
        imdb_id=movie.imdb_id,
        title=movie.title,
        original_title=movie.original_title,
        year=movie.year,
        rating=movie.rating,
        rating_count=movie.rating_count,
        imdb_rating=movie.imdb_rating,
        imdb_rating_count=movie.imdb_rating_count,
        type=movie.type,
        genres=sorted(
            association.genre_obj.name
            for association in movie.genres
            if association.genre_obj is not None
        ),
        regions=sorted(
            association.region_obj.name
            for association in movie.regions
            if association.region_obj is not None
        ),
        updated_at=movie.updated_at,
    )
    return FavoriteResponse(
        movie=movie_response,
        created_at=favorite.created_at,
        note=favorite.note or "",
    )


def _favorite_query():
    return select(Favorite).options(
        selectinload(Favorite.movie).selectinload(
            Movie.genres
        ).selectinload(MovieGenre.genre_obj),
        selectinload(Favorite.movie).selectinload(
            Movie.regions
        ).selectinload(MovieRegion.region_obj),
    )


@router.get("", response_model=list[FavoriteResponse])
@limiter.limit(settings.rate_limit_search)
def list_favorites(
    request: Request,
    db: Session = Depends(get_db),
) -> list[FavoriteResponse]:
    """List saved movies, newest favorites first."""
    favorites = db.scalars(
        _favorite_query().order_by(
            Favorite.created_at.desc(),
            Favorite.movie_id.desc(),
        )
    ).all()
    return [_response(item) for item in favorites]


@router.put("/{movie_id}", response_model=FavoriteResponse)
@limiter.limit(settings.rate_limit_search)
def add_favorite(
    request: Request,
    movie_id: int,
    payload: FavoriteUpsert,
    db: Session = Depends(get_db),
) -> FavoriteResponse:
    """Add a movie to favorites or update its note idempotently."""
    movie = db.scalar(
        select(Movie)
        .options(
            selectinload(Movie.genres).selectinload(MovieGenre.genre_obj),
            selectinload(Movie.regions).selectinload(MovieRegion.region_obj),
        )
        .where(Movie.id == movie_id)
    )
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    favorite = db.get(Favorite, movie_id)
    if favorite is None:
        favorite = Favorite(movie_id=movie_id, note=payload.note)
        db.add(favorite)
    else:
        favorite.note = payload.note

    db.commit()
    db.refresh(favorite)
    favorite.movie = movie
    return _response(favorite)


@router.delete("/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_search)
def remove_favorite(
    request: Request,
    movie_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Remove one favorite using the MovieHub internal movie ID."""
    favorite = db.get(Favorite, movie_id)
    if favorite is None:
        raise HTTPException(status_code=404, detail="Favorite not found")

    movie = db.get(Movie, movie_id)
    removed_external = False
    if movie is not None:
        if movie.tmdb_id and movie.tmdb_id.isdigit():
            removed_external = provider_response_cache.delete_favorite(
                movie.type, int(movie.tmdb_id)
            ) or removed_external
        if movie.imdb_id:
            removed_external = provider_response_cache.delete_favorite_by_imdb(
                movie.type, movie.imdb_id
            ) or removed_external

    db.delete(favorite)
    db.commit()
    if removed_external:
        try:
            provider_response_cache.backup_daily(
                settings.backup_dir / "discovery", 7, True
            )
        except Exception:
            # Favorite deletion has already committed; a backup refresh failure
            # must not turn the successful user action into an API error.
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ExternalFavoriteSnapshot(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    original_title: str | None = Field(default=None, max_length=256)
    year: int | None = Field(default=None, ge=1870, le=2100)
    rating: float | None = Field(default=None, ge=0, le=10)
    rating_count: int = Field(default=0, ge=0)
    poster_path: str | None = Field(default=None, max_length=512)
    backdrop_path: str | None = Field(default=None, max_length=512)
    imdb_id: str | None = Field(default=None, max_length=32)
    directors: list[str] = Field(default_factory=list, max_length=20)


class ExternalFavoritePayload(BaseModel):
    snapshot: ExternalFavoriteSnapshot
    note: str = Field(default="", max_length=1000)


def _normalize_identity(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in normalized if char.isalnum())


def _linked_chart_movie(
    db: Session,
    media_type: str,
    provider_id: int,
    imdb_id: str | None = None,
    title: str | None = None,
    original_title: str | None = None,
    year: int | None = None,
    directors: list[str] | None = None,
) -> Movie | None:
    identity_filter = Movie.tmdb_id == str(provider_id)
    if imdb_id:
        identity_filter = identity_filter | (Movie.imdb_id == imdb_id)
    linked = db.query(Movie).filter(
        Movie.type == media_type,
        identity_filter,
    ).first()
    if linked is not None:
        return linked

    # Fallback is intentionally strict: title + exact year + at least one
    # matching director, and exactly one local candidate must satisfy all.
    source_titles = {
        _normalize_identity(value)
        for value in (title, original_title)
        if _normalize_identity(value)
    }
    source_directors = {
        _normalize_identity(value) for value in (directors or [])
        if _normalize_identity(value)
    }
    if not source_titles or not source_directors or year is None:
        return None

    matches: list[Movie] = []
    candidates = db.query(Movie).filter(
        Movie.type == media_type,
        Movie.year == year,
    ).all()
    for movie in candidates:
        local_titles = {
            _normalize_identity(movie.title),
            _normalize_identity(movie.original_title),
        } - {""}
        if not source_titles.intersection(local_titles):
            continue
        try:
            raw_directors = json.loads(movie.directors or "[]")
        except (TypeError, json.JSONDecodeError):
            raw_directors = []
        local_directors = {
            _normalize_identity(value)
            for value in raw_directors
            if isinstance(value, str) and _normalize_identity(value)
        } if isinstance(raw_directors, list) else set()
        if source_directors.intersection(local_directors):
            matches.append(movie)
    return matches[0] if len(matches) == 1 else None


async def _enrich_external_favorites(favorites: list[dict]) -> list[dict]:
    """Resolve missing IMDb IDs and attach ratings before the UI reads favorites."""
    async def resolve_one(favorite: dict) -> None:
        snapshot = favorite.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("imdb_id"):
            return
        media_type = favorite.get("media_type")
        provider_id = favorite.get("provider_id")
        if media_type not in ("movie", "tv") or not isinstance(provider_id, int):
            return
        try:
            external = await tmdb_client.get_json(
                f"/{media_type}/{provider_id}/external_ids", {}, DETAIL_TTL
            )
            imdb_id = (external or {}).get("imdb_id")
            if isinstance(imdb_id, str) and imdb_id.startswith("tt") and len(imdb_id) <= 32:
                snapshot["imdb_id"] = imdb_id
        except Exception as exc:
            logger.info(
                "External favorite IMDb ID enrichment unavailable for TMDB %s/%s: %s",
                media_type, provider_id, type(exc).__name__,
            )

    await asyncio.gather(*(resolve_one(favorite) for favorite in favorites))
    imdb_ids = [
        snapshot.get("imdb_id")
        for favorite in favorites
        if isinstance((snapshot := favorite.get("snapshot")), dict)
        and isinstance(snapshot.get("imdb_id"), str)
    ]
    ratings = await asyncio.to_thread(lookup_ratings, imdb_ids) if imdb_ids else {}
    for favorite in favorites:
        snapshot = favorite.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        indexed = ratings.get(snapshot.get("imdb_id"))
        if indexed is not None:
            snapshot["imdb_rating"], snapshot["imdb_rating_count"] = indexed
    return favorites


@router.get("/external")
@limiter.limit("30/minute")
async def list_external_favorites(request: Request) -> list[dict]:
    """List TMDB favorites enriched with the same local IMDb index as details."""
    favorites = await asyncio.to_thread(provider_response_cache.list_favorites)
    return await _enrich_external_favorites(favorites)


@router.get("/external/status/{media_type}/{provider_id}")
@limiter.limit("60/minute")
def external_favorite_status(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    imdb_id: str | None = Query(None, max_length=32),
    title: str | None = Query(None, max_length=256),
    original_title: str | None = Query(None, max_length=256),
    year: int | None = Query(None, ge=1870, le=2100),
    directors: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    linked_movie = _linked_chart_movie(
        db, media_type, provider_id, imdb_id, title, original_title, year, directors
    )
    local_saved = (
        linked_movie is not None
        and db.get(Favorite, linked_movie.id) is not None
    )
    external_saved = provider_response_cache.has_favorite(media_type, provider_id)
    return {"is_favorite": local_saved or external_saved}


@router.put("/external/{media_type}/{provider_id}")
@limiter.limit("30/minute")
def save_external_favorite(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    payload: ExternalFavoritePayload,
    db: Session = Depends(get_db),
) -> dict:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    snapshot = payload.snapshot.model_dump()
    linked_movie = _linked_chart_movie(
        db,
        media_type,
        provider_id,
        snapshot.get("imdb_id"),
        snapshot.get("title"),
        snapshot.get("original_title"),
        snapshot.get("year"),
        snapshot.get("directors", []),
    )
    if linked_movie is not None:
        if db.get(Favorite, linked_movie.id) is None:
            db.add(Favorite(movie_id=linked_movie.id, note=payload.note))
            db.commit()
        # A chart-backed movie has one canonical Favorite row; do not create
        # a second provider-cache favorite for the same work.
        # The local Favorite row is already committed. If external cleanup
        # fails, propagate the error so the caller can retry this idempotent
        # operation; silently reporting success would leave duplicate favorites.
        provider_response_cache.delete_favorite(media_type, provider_id)
        return {"linked_movie_id": linked_movie.id, "is_favorite": True}
    saved = provider_response_cache.save_favorite(
        media_type, provider_id, snapshot, payload.note
    )
    try:
        provider_response_cache.backup_daily(
            settings.backup_dir / "discovery", 7, True
        )
    except Exception:
        pass
    return saved


@router.delete(
    "/external/{media_type}/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
def remove_external_favorite(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    db: Session = Depends(get_db),
) -> Response:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    removed_external = provider_response_cache.delete_favorite(
        media_type, provider_id
    )
    imdb_id = request.query_params.get("imdb_id")
    title = request.query_params.get("title")
    original_title = request.query_params.get("original_title")
    try:
        year = int(request.query_params["year"]) if request.query_params.get("year") else None
    except ValueError:
        year = None
    directors = request.query_params.getlist("directors")
    linked_movie = _linked_chart_movie(
        db, media_type, provider_id, imdb_id, title, original_title, year, directors
    )
    linked = (
        [db.get(Favorite, linked_movie.id)]
        if linked_movie is not None and db.get(Favorite, linked_movie.id) is not None
        else []
    )
    for favorite in linked:
        db.delete(favorite)
    if linked:
        db.commit()
    if not removed_external and not linked:
        raise HTTPException(status_code=404, detail="Favorite not found")
    if removed_external:
        try:
            provider_response_cache.backup_daily(
                settings.backup_dir / "discovery", 7, True
            )
        except Exception:
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)
