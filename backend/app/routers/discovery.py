"""Online movie and TV discovery endpoints backed by TMDB."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from app.limiter import limiter
from app.services.provider_cache import provider_response_cache
from app.services.tmdb_client import DETAIL_TTL, GENRE_TTL, SEARCH_TTL, tmdb_client

router = APIRouter(prefix="/discovery", tags=["discovery"])


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


@router.get("/search")
@limiter.limit("30/minute")
async def search_online(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    media_type: Literal["all", "movie", "tv"] = Query("all"),
    page: int = Query(1, ge=1, le=500),
    language: str = Query("zh-CN", min_length=2, max_length=12),
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
    region: str | None = Query(None, min_length=2, max_length=2),
    year: int | None = Query(None, ge=1870, le=2100),
    min_rating: float | None = Query(None, ge=0, le=10),
    min_votes: int = Query(100, ge=0, le=10000000),
    sort_by: Literal["popularity.desc", "vote_average.desc", "primary_release_date.desc", "vote_count.desc"] = Query("popularity.desc"),
    language: str = Query("zh-CN", min_length=2, max_length=12),
) -> dict:
    params = {
        "page": page,
        "with_genres": with_genres,
        "with_origin_country": region,
        "primary_release_year" if media_type == "movie" else "first_air_date_year": year,
        "vote_average.gte": min_rating,
        "vote_count.gte": min_votes,
        "sort_by": sort_by,
        "language": language,
        "include_adult": "false",
    }
    payload = await tmdb_client.get_json(f"/discover/{media_type}", params, SEARCH_TTL)
    return {
        "provider": "tmdb",
        "media_type": media_type,
        "page": page,
        "total_pages": min(int(payload.get("total_pages") or 0), 500),
        "total_results": int(payload.get("total_results") or 0),
        "items": [
            _normalize_result(item, media_type)
            for item in payload.get("results", [])
            if isinstance(item.get("id"), int)
        ],
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


@router.get("/{media_type}/{provider_id}")
@limiter.limit("30/minute")
async def get_online_detail(
    request: Request,
    media_type: Literal["movie", "tv"],
    provider_id: int,
    language: str = Query("zh-CN", min_length=2, max_length=12),
) -> dict:
    if provider_id < 1:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID")
    payload = await tmdb_client.get_json(
        f"/{media_type}/{provider_id}",
        {"language": language, "append_to_response": "credits,external_ids"},
        DETAIL_TTL,
    )
    return {
        "provider": "tmdb",
        "media_type": media_type,
        "provider_id": provider_id,
        "title": payload.get("title") or payload.get("name"),
        "original_title": payload.get("original_title") or payload.get("original_name"),
        "year": int((payload.get("release_date") or payload.get("first_air_date") or "")[:4]) if (payload.get("release_date") or payload.get("first_air_date") or "")[:4].isdigit() else None,
        "rating": payload.get("vote_average"),
        "rating_count": payload.get("vote_count", 0),
        "poster_path": payload.get("poster_path"),
        "backdrop_path": payload.get("backdrop_path"),
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
async def get_cache_stats(request: Request) -> dict[str, int]:
    return provider_response_cache.stats()
