"""Online movie and TV discovery endpoints backed by TMDB."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.config import settings
from app.database import Favorite, Movie, database_is_ready, get_db
from app.limiter import limiter
from app.dependencies.auth import verify_api_key
from app.services.provider_cache import provider_response_cache
from app.services.tmdb_client import DETAIL_TTL, GENRE_TTL, SEARCH_TTL, tmdb_client

def get_optional_db():
    """Provide local rating lookup when the private MovieHub DB is initialized."""
    if not database_is_ready():
        yield None
        return
    yield from get_db()


router = APIRouter(prefix="/discovery", tags=["discovery"])
logger = logging.getLogger("moviehub.discovery")


async def _backup_favorites_after_write() -> None:
    try:
        await asyncio.to_thread(
            provider_response_cache.backup_daily,
            settings.backup_dir / "discovery",
            7,
            True,
        )
    except Exception:
        logger.exception("Unable to refresh discovery favorites backup")



class FavoriteSnapshot(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    original_title: str | None = Field(default=None, max_length=256)
    year: int | None = Field(default=None, ge=1870, le=2100)
    rating: float | None = Field(default=None, ge=0, le=10)
    rating_count: int = Field(default=0, ge=0)
    poster_path: str | None = Field(default=None, max_length=512)
    backdrop_path: str | None = Field(default=None, max_length=512)
    imdb_id: str | None = Field(default=None, max_length=32)


class ExternalFavoritePayload(BaseModel):
    snapshot: FavoriteSnapshot
    note: str = Field(default="", max_length=1000)


def _normalize_result(item: dict, media_type: str) -> dict:
    title = item.get("title") or item.get("name") or ""
    original_title = item.get("original_title") or item.get("original_name")
    date_value = item.get("release_date") or item.get("first_air_date") or ""
    year = int(date_value[:4]) if isinstance(date_value, str) and len(date_value) >= 4 and date_value[:4].isdigit() else None
    return {
        "provider": "tmdb",
        "provider_id": int(item["id"]),
        "media_type": media_type,
        "title": str(title)[:256],
        "original_title": str(original_title)[:256] if original_title else None,
        "year": year,
        "rating": item.get("vote_average"),
        "rating_count": item.get("vote_count", 0),
        "poster_path": item.get("poster_path"),
        "backdrop_path": item.get("backdrop_path"),
        "genre_ids": item.get("genre_ids", []),
    }


def _attach_local_imdb_ratings(db: Session | None, items: list[dict]) -> list[dict]:
    """Attach ratings only through an exact local TMDB-ID identity match."""
    if db is None:
        for item in items:
            item["imdb_rating"] = None
            item["imdb_rating_count"] = None
        return items
    provider_ids = {str(item["provider_id"]) for item in items if isinstance(item.get("provider_id"), int)}
    media_types = {item.get("media_type") for item in items}
    if not provider_ids or not media_types:
        return items
    local_movies = db.query(Movie).filter(
        Movie.tmdb_id.in_(provider_ids),
        Movie.type.in_(media_types),
    ).all()
    by_identity = {(movie.type, movie.tmdb_id): movie for movie in local_movies if movie.tmdb_id}
    for item in items:
        movie = by_identity.get((item.get("media_type"), str(item.get("provider_id"))))
        item["imdb_rating"] = movie.imdb_rating if movie else None
        item["imdb_rating_count"] = movie.imdb_rating_count if movie else None
    return items
@router.get("/search")
@limiter.limit("30/minute")
async def search_online(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    media_type: Literal["all", "movie", "tv"] = Query("all"),
    page: int = Query(1, ge=1, le=500),
    language: str = Query("zh-CN", min_length=2, max_length=12),
    db: Session | None = Depends(get_optional_db),
) -> dict:
    """Search one requested page only; never crawl subsequent pages."""
    query = " ".join(q.split())
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query must contain at least 2 characters")
    endpoint = "/search/multi" if media_type == "all" else f"/search/{media_type}"
    payload = await tmdb_client.get_json(
        endpoint,
        {"query": query, "page": page, "language": language, "include_adult": "false"},
        SEARCH_TTL,
    )
    results = []
    for item in payload.get("results", []):
        kind = item.get("media_type") if media_type == "all" else media_type
        if kind not in ("movie", "tv") or not isinstance(item.get("id"), int):
            continue
        results.append(_normalize_result(item, kind))
    _attach_local_imdb_ratings(db, results)
    return {
        "provider": "tmdb",
        "query": query,
        "page": page,
        "total_pages": min(int(payload.get("total_pages") or 0), 500),
        "total_results": int(payload.get("total_results") or 0),
        "items": results,
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


@router.get("/genres")
@limiter.limit("30/minute")
async def get_online_genres(
    request: Request,
    media_type: Literal["movie", "tv"] = Query("movie"),
    language: str = Query("zh-CN", min_length=2, max_length=12),
) -> dict:
    payload = await tmdb_client.get_json(
        f"/genre/{media_type}/list", {"language": language}, GENRE_TTL
    )
    return {"provider": "tmdb", "media_type": media_type, "genres": payload.get("genres", [])}


@router.get("/regions")
@limiter.limit("30/minute")
async def get_online_regions(request: Request, language: str = Query("zh-CN", min_length=2, max_length=12)) -> dict:
    payload = await tmdb_client.get_json(
        "/configuration/countries", {"language": language}, GENRE_TTL
    )
    return {
        "provider": "tmdb",
        "regions": [
            {"code": item.get("iso_3166_1"), "name": item.get("native_name") or item.get("english_name")}
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("iso_3166_1")
        ],
    }


@router.get("/discover")
@limiter.limit("30/minute")
async def discover_online(
    request: Request,
    media_type: Literal["movie", "tv"] = Query("movie"),
    page: int = Query(1, ge=1, le=500),
    with_genres: str | None = Query(None, max_length=64),
    region: str | None = Query(None, min_length=2, max_length=32),
    year: int | None = Query(None, ge=1870, le=2100),
    min_year: int | None = Query(None, ge=1870, le=2100),
    max_year: int | None = Query(None, ge=1870, le=2100),
    min_rating: float | None = Query(None, ge=0, le=10),
    min_votes: int = Query(100, ge=0, le=10000000),
    max_votes: int | None = Query(None, ge=0, le=10000000),
    sort_by: Literal["popularity.desc", "vote_average.desc", "vote_average.asc", "primary_release_date.desc", "first_air_date.desc", "vote_count.desc"] = Query("popularity.desc"),
    language: str = Query("zh-CN", min_length=2, max_length=12),
    db: Session = Depends(get_db),
) -> dict:
    params = {
        "page": page,
        "with_genres": with_genres,
        "with_origin_country": region,
        "primary_release_year" if media_type == "movie" else "first_air_date_year": year if year is not None else (min_year if min_year == max_year else None),
        "primary_release_date.gte" if media_type == "movie" else "first_air_date.gte": (str(min_year) + "-01-01") if min_year is not None and year is None else None,
        "primary_release_date.lte" if media_type == "movie" else "first_air_date.lte": (str(max_year) + "-12-31") if max_year is not None and year is None else None,
        "vote_average.gte": min_rating,
        "vote_count.gte": min_votes,
        "vote_count.lte": max_votes,
        "sort_by": sort_by,
        "language": language,
        "include_adult": "false",
    }
    payload = await tmdb_client.get_json(f"/discover/{media_type}", params, SEARCH_TTL)
    results = [_normalize_result(item, media_type) for item in payload.get("results", []) if isinstance(item.get("id"), int)]
    _attach_local_imdb_ratings(db, results)
    return {
        "provider": "tmdb",
        "media_type": media_type,
        "page": page,
        "total_pages": min(int(payload.get("total_pages") or 0), 500),
        "total_results": int(payload.get("total_results") or 0),
        "items": results,
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


@router.get("/favorites/status/{media_type}/{provider_id}", dependencies=[Depends(verify_api_key)])
@limiter.limit("60/minute")
async def get_favorite_status(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    imdb_id: str | None = Query(None, max_length=32),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Check one TMDB identity against both online and linked chart favorites."""
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    identity_filter = Movie.tmdb_id == str(provider_id)
    if imdb_id:
        identity_filter = identity_filter | (Movie.imdb_id == imdb_id)
    local_saved = db.query(Favorite).join(Movie).filter(
        Movie.type == media_type,
        identity_filter,
    ).first() is not None
    external_saved = await asyncio.to_thread(
        provider_response_cache.has_favorite, media_type, provider_id
    )
    return {"is_favorite": local_saved or external_saved}


@router.get("/{media_type}/{provider_id}")
@limiter.limit("30/minute")
async def get_online_detail(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    language: str = Query("zh-CN", min_length=2, max_length=12),
    db: Session = Depends(get_db),
) -> dict:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    payload = await tmdb_client.get_json(
        f"/{media_type}/{provider_id}",
        {"language": language, "append_to_response": "credits,external_ids"},
        DETAIL_TTL,
        include_overview=True,
    )
    imdb_id = (payload.get("external_ids") or {}).get("imdb_id")
    identity_filter = Movie.tmdb_id == str(provider_id)
    if imdb_id:
        identity_filter = identity_filter | (Movie.imdb_id == imdb_id)
    local_movie = db.query(Movie).filter(Movie.type == media_type, identity_filter).first() if db is not None else None
    return {
        "provider": "tmdb",
        "media_type": media_type,
        "provider_id": provider_id,
        "imdb_rating": local_movie.imdb_rating if local_movie else None,
        "imdb_rating_count": local_movie.imdb_rating_count if local_movie else None,
        "title": payload.get("title") or payload.get("name"),
        "original_title": payload.get("original_title") or payload.get("original_name"),
        "year": int((payload.get("release_date") or payload.get("first_air_date") or "")[:4]) if (payload.get("release_date") or payload.get("first_air_date") or "")[:4].isdigit() else None,
        "rating": payload.get("vote_average"),
        "rating_count": payload.get("vote_count", 0),
        "overview": payload.get("overview") or None,
        "poster_path": payload.get("poster_path"),
        "backdrop_path": payload.get("backdrop_path"),
        "genre_ids": [item.get("id") for item in payload.get("genres", []) if isinstance(item, dict) and isinstance(item.get("id"), int)],
        "genres": payload.get("genres", []),
        "production_countries": payload.get("production_countries", payload.get("origin_country", [])),
        "runtime": payload.get("runtime"),
        "number_of_seasons": payload.get("number_of_seasons"),
        "number_of_episodes": payload.get("number_of_episodes"),
        "credits": payload.get("credits", {}),
        "external_ids": payload.get("external_ids", {}),
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


@router.get("/cache-stats")
@limiter.limit("10/minute")
async def get_cache_stats(request: Request) -> dict[str, int | float]:
    cache_stats = await asyncio.to_thread(provider_response_cache.stats)
    return {**cache_stats, **tmdb_client.stats()}


@router.get("/favorites", dependencies=[Depends(verify_api_key)])
@limiter.limit("30/minute")
async def list_external_favorites(request: Request) -> list[dict]:
    return await asyncio.to_thread(provider_response_cache.list_favorites)


@router.put("/favorites/{media_type}/{provider_id}", dependencies=[Depends(verify_api_key)])
@limiter.limit("30/minute")
async def save_external_favorite(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    payload: ExternalFavoritePayload,
    db: Session = Depends(get_db),
) -> dict:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    snapshot = payload.snapshot.model_dump()
    # A user-initiated online favorite links to an existing chart movie by
    # provider identity; it never creates a new Movie/catalogue row.
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

    saved = await asyncio.to_thread(
        provider_response_cache.save_favorite,
        media_type,
        provider_id,
        snapshot,
        payload.note,
    )
    await _backup_favorites_after_write()
    return saved


@router.delete("/favorites/{media_type}/{provider_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(verify_api_key)])
@limiter.limit("30/minute")
async def remove_external_favorite(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    db: Session = Depends(get_db),
) -> Response:
    removed_external = await asyncio.to_thread(
        provider_response_cache.delete_favorite, media_type, provider_id
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
        await _backup_favorites_after_write()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
