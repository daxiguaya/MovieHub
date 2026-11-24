
"""Normalized input schemas for chart snapshot imports."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.chart_definitions import get_chart_definition


class ChartMovieImport(BaseModel):
    """One movie entry in a normalized chart snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    douban_id: str = Field(min_length=1, max_length=64)

    rank: int = Field(ge=1)
    source_rating: float | None = Field(default=None, ge=0, le=10)

    title: str = Field(min_length=1, max_length=256)
    original_title: str | None = Field(default=None, max_length=256)

    year: int | None = Field(default=None, ge=1870, le=2200)
    rating: float | None = Field(default=None, ge=0, le=10)
    rating_count: int | None = Field(default=None, ge=0)

    type: Literal["movie", "tv"] = "movie"

    imdb_id: str | None = Field(default=None, max_length=32)
    tmdb_id: str | None = Field(default=None, max_length=32)

    directors: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    posters: list[str] = Field(default_factory=list)

    overview: str | None = None
    douban_url: str | None = Field(default=None, max_length=512)

    @field_validator("douban_id")
    @classmethod
    def validate_douban_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[0-9]{1,32}", value):
            raise ValueError("douban_id must contain only digits")
        return value

    @field_validator(
        "directors",
        "actors",
        "genres",
        "regions",
        "posters",
    )
    @classmethod
    def normalize_string_lists(
        cls,
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue

            result.append(normalized)
            seen.add(normalized)

        return result


class ChartSnapshotImport(BaseModel):
    """A complete, normalized snapshot for one chart."""

    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str = Field(min_length=1, max_length=96)
    name: str = Field(min_length=1, max_length=160)

    source: str = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=32)

    period: str | None = Field(default=None, max_length=32)
    description: str | None = None

    snapshot_date: date

    movies: list[ChartMovieImport] = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", value):
            raise ValueError(
                "slug may contain lowercase letters, digits and hyphens"
            )
        return value

    @model_validator(mode="after")
    def validate_unique_entries(self):
        douban_ids = [movie.douban_id for movie in self.movies]
        ranks = [movie.rank for movie in self.movies]

        if len(douban_ids) != len(set(douban_ids)):
            raise ValueError("duplicate douban_id in chart snapshot")

        if len(ranks) != len(set(ranks)):
            raise ValueError("duplicate rank in chart snapshot")

        # Built-in chart slugs have a stable taxonomy. Reject cross-period,
        # cross-category and movie/TV mismatches before database access.
        definition = get_chart_definition(self.slug)
        if definition is not None:
            if self.category != definition.category:
                raise ValueError(
                    f"chart {self.slug} requires category={definition.category!r}"
                )
            if self.period != definition.period:
                raise ValueError(
                    f"chart {self.slug} requires period={definition.period!r}"
                )
            if any(movie.type != definition.media_type for movie in self.movies):
                raise ValueError(
                    f"chart {self.slug} accepts only {definition.media_type!r} entries"
                )

        return self

