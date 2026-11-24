
"""Movie API endpoints for MovieHub."""

import asyncio
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urljoin, urlsplit
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import (
    Genre,
    Movie,
    MovieGenre,
    MoviePoster,
    MovieRegion,
    Region,
    get_db,
)
from app.limiter import limiter
from app.schemas import (
    GenreCount,
    MovieDetailResponse,
    MoviesListResponse,
    RegionCount,
    StatsResponse,
)
from app.services.movie_service import movie_service
from app.services.poster_service import poster_cache_service

logger = logging.getLogger("moviehub.movies")

router = APIRouter(prefix="/movies", tags=["movies"])

POSTER_CACHE_MAX_AGE = 30 * 24 * 60 * 60


def _parse_json_list(value: str | list | None) -> list[str]:
    """Convert a JSON-encoded list or Python list into a string list."""
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]

    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [value.strip()] if isinstance(value, str) and value.strip() else []

    if not isinstance(parsed, list):
        return []

    result: list[str] = []
    for item in parsed:
        if item is None:
            continue

        if isinstance(item, dict):
            # Some metadata sources represent people as {"name": "..."}.
            name = item.get("name")
            if name:
                result.append(str(name).strip())
        elif str(item).strip():
            result.append(str(item).strip())

    return result


def _get_movie_detail(movie: Movie) -> MovieDetailResponse:
    """Build a complete movie detail response from an ORM object."""
    douban_id = movie.douban_id

    return MovieDetailResponse(
        id=movie.id,
        douban_id=douban_id,
        title=movie.title,
        original_title=movie.original_title,
        year=movie.year,
        rating=movie.rating,
        rating_count=movie.rating_count or 0,
        type=movie.type,
        genres=[
            association.genre_obj.name
            for association in movie.genres
            if association.genre_obj is not None
        ],
        regions=[
            association.region_obj.name
            for association in movie.regions
            if association.region_obj is not None
        ],
        updated_at=movie.updated_at,
        imdb_id=movie.imdb_id,
        tmdb_id=movie.tmdb_id,
        directors=_parse_json_list(movie.directors),
        actors=_parse_json_list(movie.actors),
        overview=movie.overview,
        douban_url=(
            movie.douban_url
            or (
                f"https://movie.douban.com/subject/{douban_id}/"
                if douban_id
                else None
            )
        ),
        posters=[poster.url for poster in movie.posters],
    )


@router.get("", response_model=MoviesListResponse)
@limiter.limit(settings.rate_limit_search)
def get_movies(
    request: Request,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=20, description="Number of items per page"),
    type: Literal["movie", "tv"] | None = Query(None, description="Filter by type"),
    min_rating: float | None = Query(None, ge=0, le=10),
    max_rating: float | None = Query(None, ge=0, le=10),
    min_rating_count: int | None = Query(None, ge=0),
    min_year: int | None = Query(None),
    max_year: int | None = Query(None),
    genres: str | None = Query(None, description="Comma-separated genres (AND logic)"),
    exclude_genres: str | None = Query(
        None,
        description="Comma-separated genres to exclude",
    ),
    regions: str | None = Query(None, description="Comma-separated regions (OR logic)"),
    search: str | None = Query(None, description="Search movie title"),
    sort_by: Literal["rating", "rating_count", "year"] = Query("rating_count"),
    sort_order: Literal["asc", "desc"] = Query("desc"),
    db: Session = Depends(get_db),
) -> MoviesListResponse:
    """Get movies with filtering and cursor pagination."""
    return movie_service.get_movies(
        db=db,
        cursor=cursor,
        limit=limit,
        type=type,
        min_rating=min_rating,
        max_rating=max_rating,
        min_rating_count=min_rating_count,
        min_year=min_year,
        max_year=max_year,
        genres=genres.split(",") if genres else None,
        exclude_genres=exclude_genres.split(",") if exclude_genres else None,
        regions=regions.split(",") if regions else None,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/genres", response_model=list[GenreCount])
@limiter.limit(settings.rate_limit_genres)
def get_genres(
    request: Request,
    type: Literal["movie", "tv"] | None = Query(None),
    db: Session = Depends(get_db),
) -> list[GenreCount]:
    """Get all genres with movie counts."""
    return movie_service.get_genres(db, type)


@router.get("/regions", response_model=list[RegionCount])
@limiter.limit(settings.rate_limit_regions)
def get_regions(
    request: Request,
    type: Literal["movie", "tv"] | None = Query(None),
    db: Session = Depends(get_db),
) -> list[RegionCount]:
    """Get all regions with movie counts."""
    return movie_service.get_regions(db, type)


@router.get("/stats", response_model=StatsResponse)
@limiter.limit(settings.rate_limit_stats)
def get_stats(
    request: Request,
    db: Session = Depends(get_db),
) -> StatsResponse:
    """Get database statistics."""
    return movie_service.get_stats(db)


@router.get("/id/{movie_id:int}", response_model=MovieDetailResponse)
@limiter.limit(settings.rate_limit_search)
def get_movie_detail_by_internal_id(
    request: Request,
    movie_id: int,
    db: Session = Depends(get_db),
) -> MovieDetailResponse:
    """Get a movie detail by MovieHub's stable internal ID."""
    movie = (
        db.query(Movie)
        .options(
            selectinload(Movie.genres).selectinload(MovieGenre.genre_obj),
            selectinload(Movie.regions).selectinload(MovieRegion.region_obj),
            selectinload(Movie.posters),
        )
        .filter(Movie.id == movie_id)
        .first()
    )
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return _get_movie_detail(movie)


@router.get("/{douban_id}", response_model=MovieDetailResponse)
@limiter.limit(settings.rate_limit_search)
def get_movie_detail(
    request: Request,
    douban_id: str,
    db: Session = Depends(get_db),
) -> MovieDetailResponse:
    """Get a movie detail by its Douban subject ID."""
    if not douban_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid Douban ID")

    movie = (
        db.query(Movie)
        .options(
            selectinload(Movie.genres).selectinload(MovieGenre.genre_obj),
            selectinload(Movie.regions).selectinload(MovieRegion.region_obj),
            selectinload(Movie.posters),
        )
        .filter(Movie.douban_id == douban_id)
        .first()
    )

    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    return _get_movie_detail(movie)


def _get_poster_candidates(base_urls: list[str]) -> list[str]:
    """Generate poster URL candidates with Douban CDN mirror fallbacks."""
    candidates: list[str] = []

    for base_url in base_urls:
        if base_url not in candidates:
            candidates.append(base_url)

        match = re.search(r"img([0-9]+)\.doubanio\.com", base_url)
        if not match:
            continue

        original_host = match.group(0)

        for mirror in ("img1.doubanio.com", "img2.doubanio.com", "img3.doubanio.com"):
            if mirror == original_host:
                continue

            fallback_url = base_url.replace(original_host, mirror)
            if fallback_url not in candidates:
                candidates.append(fallback_url)

    return candidates


POSTER_MAX_BYTES = 8 * 1024 * 1024
POSTER_MAX_REDIRECTS = 3
_ALLOWED_POSTER_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}


def _poster_bytes_match_content_type(content: bytes, content_type: str) -> bool:
    """Require a matching raster-image file signature, not just a server header."""
    if not content:
        return False
    if content_type == "image/jpeg":
        return content.startswith(bytes.fromhex("ffd8ff"))
    if content_type == "image/png":
        return content.startswith(bytes.fromhex("89504e470d0a1a0a"))
    if content_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return (
            len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )
    if content_type == "image/avif":
        return (
            len(content) >= 12
            and content[4:8] == b"ftyp"
            and content[8:12] in (b"avif", b"avis")
        )
    return False

def _is_allowed_poster_url(url: str) -> bool:
    """Allow only HTTPS Douban image CDN hosts, never arbitrary URLs."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and re.fullmatch(r"img[0-9]+\.doubanio\.com", host) is not None
        )
    except ValueError:
        return False


def _all_resolved_addresses_are_public(addresses: list[str]) -> bool:
    """Reject DNS answers containing loopback, private, link-local or reserved IPs."""
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        return False


async def _poster_host_resolves_publicly(url: str) -> bool:
    """Resolve each allowlisted CDN host and reject any non-public address."""
    try:
        parsed = urlsplit(url)
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
        addresses = list({record[4][0] for record in records})
        return _all_resolved_addresses_are_public(addresses)
    except (OSError, ValueError):
        return False


async def _download_poster_image(
    url: str,
) -> tuple[bytes, str] | None:
    """Download a bounded raster image while validating every redirect hop."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://movie.douban.com/",
    }

    current_url = url
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        follow_redirects=False,
    ) as client:
        for redirect_count in range(POSTER_MAX_REDIRECTS + 1):
            if not _is_allowed_poster_url(current_url):
                logger.warning("Rejected poster URL outside the Douban image CDN allowlist")
                return None
            if not await _poster_host_resolves_publicly(current_url):
                logger.warning("Rejected poster CDN host resolving to a non-public address")
                return None

            try:
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location or redirect_count >= POSTER_MAX_REDIRECTS:
                            return None
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", maxsplit=1)[0]
                        .strip()
                        .lower()
                    )
                    if content_type not in _ALLOWED_POSTER_CONTENT_TYPES:
                        return None

                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > POSTER_MAX_BYTES:
                                logger.warning("Rejected oversized poster response")
                                return None
                        except ValueError:
                            return None

                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > POSTER_MAX_BYTES:
                            logger.warning("Aborted oversized poster response")
                            return None
                        chunks.append(chunk)

                    body = b"".join(chunks)
                    if not _poster_bytes_match_content_type(body, content_type):
                        logger.warning("Rejected poster whose file signature does not match its content type")
                        return None
                    return body, content_type

            except httpx.HTTPError:
                logger.debug("Poster candidate unavailable")
                return None

    return None


@router.get("/{movie_id:int}/poster", response_model=None)
@limiter.limit(settings.rate_limit_poster)
async def get_poster(
    request: Request,
    movie_id: int,
    db: Session = Depends(get_db),
) -> FileResponse | Response:
    """Get a locally cached poster or fetch it from Douban."""
    cached_result = poster_cache_service.get_cached_poster(movie_id)

    if cached_result:
        cache_path, content_type = cached_result
        return FileResponse(
            path=cache_path,
            media_type=content_type,
            headers={
                "Cache-Control": f"public, max-age={POSTER_CACHE_MAX_AGE}",
                "X-Cache": "HIT",
                "X-Content-Type-Options": "nosniff",
            },
        )

    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    posters = (
        db.query(MoviePoster)
        .filter(MoviePoster.movie_id == movie.id)
        .all()
    )
    poster_urls = [poster.url for poster in posters]

    # Poster downloads perform asynchronous DNS and external HTTP I/O.
    # Release the synchronous SQLAlchemy connection before awaiting them so
    # concurrent cache misses cannot exhaust the database connection pool.
    db.close()

    if not poster_urls:
        raise HTTPException(status_code=404, detail="No poster available for this movie")

    downloaded: tuple[bytes, str] | None = None
    for candidate_url in _get_poster_candidates(poster_urls):
        downloaded = await _download_poster_image(candidate_url)
        if downloaded is not None:
            break

    if downloaded is None:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch a valid poster image",
        )

    content, actual_content_type = downloaded

    poster_cache_service.save_poster(
        movie_id,
        content,
        actual_content_type,
    )

    cached_result = poster_cache_service.get_cached_poster(movie_id)

    if cached_result:
        cache_path, cached_content_type = cached_result
        return FileResponse(
            path=cache_path,
            media_type=cached_content_type,
            headers={
                "Cache-Control": f"public, max-age={POSTER_CACHE_MAX_AGE}",
                "X-Cache": "MISS",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return Response(
        content=content,
        media_type=actual_content_type,
        headers={
            "Cache-Control": f"public, max-age={POSTER_CACHE_MAX_AGE}",
            "X-Cache": "MISS",
            "X-Content-Type-Options": "nosniff",
        },
    )

