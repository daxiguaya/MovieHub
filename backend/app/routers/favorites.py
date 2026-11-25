"""Single-user favorites API, keyed by MovieHub's internal movie ID."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
        rating_count=movie.rating_count or 0,
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
