"""Conservative one-shot collector for Douban's public tagged movie lists.

This is an undocumented web-application endpoint, not an official public API.
It is opt-in/manual only, checks robots.txt, paces requests, and never bypasses
access controls or retries rate-limit responses.
"""

import re
import time
from datetime import date
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.adapters.douban_top250 import (
    DOUBAN_BASE_URL,
    PAGE_MAX_BYTES,
    ROBOTS_URL,
    USER_AGENT,
    DoubanCollectionError,
    _public_poster_url,
)
from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport

SEARCH_SUBJECTS_URL = f"{DOUBAN_BASE_URL}/j/search_subjects"
PAGE_SIZE = 20
MAX_ITEMS = 100
REQUEST_DELAY_SECONDS = 2.0

CHARTS = {
    "popular": {
        "slug": "popular",
        "name": "豆瓣实时热门",
        "tag": "热门",
        "category": "popular",
        "description": "豆瓣网页热门电影列表",
    },
    "high-rated": {
        "slug": "high-rated",
        "name": "豆瓣高分榜",
        "tag": "豆瓣高分",
        "category": "rating",
        "description": "豆瓣网页高分电影列表",
    },
}


class DoubanTaggedChartCollector:
    """Collect one bounded tagged movie list from Douban's public web endpoint."""

    def __init__(
        self,
        client=None,
        sleeper: Callable[[float], None] = time.sleep,
        request_delay: float = REQUEST_DELAY_SECONDS,
        max_items: int = MAX_ITEMS,
    ) -> None:
        if request_delay < REQUEST_DELAY_SECONDS:
            raise ValueError(
                f"Request delay must be at least {REQUEST_DELAY_SECONDS} seconds"
            )
        if max_items < 1 or max_items > 500:
            raise ValueError("max_items must be between 1 and 500")
        self.client = client
        self.sleeper = sleeper
        self.request_delay = request_delay
        self.max_items = max_items

    @staticmethod
    def _check_response(response, url: str) -> str:
        status = response.status_code
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise DoubanCollectionError(
                "Douban returned HTTP 429. Collection stopped without retry"
                + (f"; Retry-After: {retry_after}" if retry_after else "")
            )
        if status in (401, 403):
            raise DoubanCollectionError(
                f"Douban denied access to {url} (HTTP {status}); no bypass is attempted"
            )
        if 300 <= status < 400:
            raise DoubanCollectionError(
                f"Unexpected redirect while requesting {url}; redirects are disabled"
            )
        if status != 200:
            raise DoubanCollectionError(
                f"Unexpected HTTP {status} while requesting {url}"
            )
        if len(response.content) > PAGE_MAX_BYTES:
            raise DoubanCollectionError(f"Response exceeded {PAGE_MAX_BYTES} bytes")
        return response.text

    @staticmethod
    def _check_robots(client) -> None:
        response = client.get(ROBOTS_URL)
        if response.status_code == 404:
            parser = RobotFileParser()
            parser.parse([])
        elif response.status_code == 200:
            if len(response.content) > 256 * 1024:
                raise DoubanCollectionError("Douban robots.txt is unexpectedly large")
            parser = RobotFileParser()
            parser.set_url(ROBOTS_URL)
            parser.parse(response.text.splitlines())
        else:
            raise DoubanCollectionError(
                f"Could not safely read robots.txt (HTTP {response.status_code})"
            )

        if not parser.can_fetch(USER_AGENT, SEARCH_SUBJECTS_URL):
            raise DoubanCollectionError(
                "Douban robots.txt disallows the tagged chart endpoint"
            )

    @staticmethod
    def _parse_subject(subject: dict, rank: int) -> ChartMovieImport:
        douban_id = str(subject.get("id") or "").strip()
        if not douban_id:
            match = re.search(
                r"/subject/([0-9]+)/",
                str(subject.get("url") or ""),
            )
            douban_id = match.group(1) if match else ""
        title = str(subject.get("title") or "").strip()
        if not douban_id.isdigit() or not title:
            raise DoubanCollectionError(
                "Tagged chart response contained a movie without a valid ID/title"
            )

        rating_text = str(subject.get("rate") or "").strip()
        try:
            rating = float(rating_text) if rating_text else None
        except ValueError:
            rating = None

        cover = _public_poster_url(str(subject.get("cover") or ""))
        source_url = str(subject.get("url") or "").strip()
        try:
            parsed_url = urlsplit(source_url)
        except ValueError:
            parsed_url = None
        if (
            parsed_url is None
            or parsed_url.scheme != "https"
            or parsed_url.hostname != "movie.douban.com"
            or parsed_url.port not in (None, 443)
            or not re.fullmatch(r"/subject/[0-9]+/?", parsed_url.path)
        ):
            source_url = f"{DOUBAN_BASE_URL}/subject/{douban_id}/"

        return ChartMovieImport(
            douban_id=douban_id,
            rank=rank,
            source_rating=rating,
            title=title,
            original_title=None,
            year=None,
            rating=rating,
            rating_count=None,
            type="movie",
            genres=[],
            regions=[],
            posters=[cover] if cover else [],
            douban_url=source_url,
        )

    def collect(self, chart_key: str, snapshot_date: date) -> ChartSnapshotImport:
        config = CHARTS.get(chart_key)
        if config is None:
            raise ValueError(f"Unsupported Douban chart: {chart_key}")

        owns_client = self.client is None
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

        try:
            self._check_robots(client)
            movies: list[ChartMovieImport] = []
            seen_ids: set[str] = set()
            page_start = 0

            while len(movies) < self.max_items:
                page_limit = min(PAGE_SIZE, self.max_items - len(movies))
                params = {
                    "type": "movie",
                    "tag": config["tag"],
                    "sort": "recommend",
                    "page_limit": page_limit,
                    "page_start": page_start,
                }
                response = client.get(SEARCH_SUBJECTS_URL, params=params)
                url = f"{SEARCH_SUBJECTS_URL}?page_start={page_start}"
                self._check_response(response, url)

                try:
                    payload = response.json()
                except ValueError as exc:
                    raise DoubanCollectionError(
                        "Douban tagged chart endpoint returned invalid JSON"
                    ) from exc

                subjects = payload.get("subjects") if isinstance(payload, dict) else None
                if not isinstance(subjects, list):
                    raise DoubanCollectionError(
                        "Douban tagged chart response has no subjects array"
                    )
                if not subjects:
                    break

                for subject in subjects:
                    if not isinstance(subject, dict):
                        raise DoubanCollectionError(
                            "Douban tagged chart returned an invalid subject record"
                        )
                    movie = self._parse_subject(subject, len(movies) + 1)
                    if movie.douban_id in seen_ids:
                        raise DoubanCollectionError(
                            "Duplicate movie ID across pages; refusing an inconsistent snapshot"
                        )
                    seen_ids.add(movie.douban_id)
                    movies.append(movie)
                    if len(movies) >= self.max_items:
                        break

                if len(subjects) < page_limit:
                    break
                page_start += page_limit
                if len(movies) < self.max_items:
                    self.sleeper(self.request_delay)

            if not movies:
                raise DoubanCollectionError(
                    "Douban tagged chart returned no movies; no snapshot was written"
                )

            return ChartSnapshotImport(
                slug=config["slug"],
                name=config["name"],
                source="douban",
                category=config["category"],
                description=config["description"],
                snapshot_date=snapshot_date,
                movies=movies,
            )
        finally:
            if owns_client:
                client.close()
