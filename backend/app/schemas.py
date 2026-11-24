
"""Pydantic schemas for MovieHub API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MovieType = Literal["movie", "tv"]


class MovieBase(BaseModel):
    """Base movie schema with common fields."""

    id: int
    douban_id: str | None = None
    tmdb_id: str | None = None
    title: str
    original_title: str | None = None
    year: int | None = None
    rating: float | None = None
    rating_count: int = 0
    type: MovieType
    genres: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class MovieResponse(MovieBase):
    """Movie card response."""

    updated_at: int | None = None

    model_config = ConfigDict(from_attributes=True)


class MovieDetailResponse(MovieResponse):
    """Detailed movie response."""

    imdb_id: str | None = None
    tmdb_id: str | None = None
    directors: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    overview: str | None = None
    douban_url: str | None = None
    posters: list[str] = Field(default_factory=list)


class MoviesListResponse(BaseModel):
    """Response schema for movie list endpoint."""

    items: list[MovieResponse]
    next_cursor: str | None = None
    total: int


class GenreCount(BaseModel):
    """Genre count schema."""

    genre: str
    count: int


class RegionCount(BaseModel):
    """Region count schema."""

    region: str
    count: int


class ImportStatus(BaseModel):
    """Import process status schema."""

    status: Literal["idle", "running", "completed", "failed"]
    run_id: str | None = None
    processed: int = 0
    total: int = 0
    errors: int = 0
    percentage: float = 0.0
    message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StatsResponse(BaseModel):
    """Database statistics response schema."""

    total_movies: int
    total_tv: int
    avg_rating: float
    total_genres: int
    total_regions: int


class ChartResponse(BaseModel):
    """Chart directory entry."""

    list_id: int
    slug: str
    name: str
    source: str
    category: str
    period: str | None = None
    description: str | None = None
    enabled: bool
    display_order: int = 0
    last_updated: datetime | None = None


class ChartSnapshotResponse(BaseModel):
    """Available dated snapshot for a chart."""

    snapshot_date: str
    imported_at: datetime
    item_count: int


class ChartMovieResponse(MovieResponse):
    """Movie card as it appears inside a chart."""

    rank: int
    source_rating: float | None = None
    snapshot_date: str


class ChartMoviesListResponse(BaseModel):
    """Paged chart snapshot response."""

    chart: ChartResponse
    items: list[ChartMovieResponse]
    next_cursor: str | None = None
    total: int


class FavoriteUpsert(BaseModel):
    """Favorite write payload for the single-user installation."""

    note: str = Field(default="", max_length=1000)


class FavoriteResponse(BaseModel):
    """A saved movie and its user-owned favorite metadata."""

    movie: MovieResponse
    created_at: datetime
    note: str = ""

class ChartRankChange(BaseModel):
    """One movie's rank movement between two chart snapshots."""

    movie_id: int
    douban_id: str | None = None
    title: str
    year: int | None = None
    type: MovieType
    before_rank: int | None = None
    after_rank: int | None = None
    rank_change: int | None = None
    status: Literal["new", "removed", "moved", "unchanged"]


class ChartCompareResponse(BaseModel):
    """Rank comparison for two dated snapshots of the same chart."""

    chart: ChartResponse
    from_date: str
    to_date: str
    total_before: int
    total_after: int
    items: list[ChartRankChange]
