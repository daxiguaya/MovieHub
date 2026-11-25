"""Single-user favorites API, keyed by MovieHub's internal movie ID."""

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
from app.services.provider_cache import provider_response_cache

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


class ExternalFavoritePayload(BaseModel):
    snapshot: ExternalFavoriteSnapshot
    note: str = Field(default="", max_length=1000)


@router.get("/external")
@limiter.limit("30/minute")
def list_external_favorites(request: Request) -> list[dict]:
    """List TMDB favorites through the same protected /favorites route family."""
    return provider_response_cache.list_favorites()


@router.get("/external/status/{media_type}/{provider_id}")
@limiter.limit("60/minute")
def external_favorite_status(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    imdb_id: str | None = Query(None, max_length=32),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    identity_filter = Movie.tmdb_id == str(provider_id)
    if imdb_id:
        identity_filter = identity_filter | (Movie.imdb_id == imdb_id)
    local_saved = db.query(Favorite).join(Movie).filter(
        Movie.type == media_type,
        identity_filter,
    ).first() is not None
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
    identity_filter = Movie.tmdb_id == str(provider_id)
    if snapshot.get("imdb_id"):
        identity_filter = identity_filter | (Movie.imdb_id == snapshot["imdb_id"])
    linked_movie = db.query(Movie).filter(
        Movie.type == media_type,
        identity_filter,
    ).first()
    if linked_movie is not None and db.get(Favorite, linked_movie.id) is None:
        db.add(Favorite(movie_id=linked_movie.id, note=payload.note))
        db.commit()
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
    identity_filter = Movie.tmdb_id == str(provider_id)
    if imdb_id and len(imdb_id) <= 32:
        identity_filter = identity_filter | (Movie.imdb_id == imdb_id)
    linked = db.query(Favorite).join(Movie).filter(
        Movie.type == media_type,
        identity_filter,
    ).all()
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
