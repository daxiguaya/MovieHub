"""Conservative one-shot collector for Douban's public Top 250 HTML pages.

No cookies, authentication, proxy rotation, challenge bypass or retries are used.
The collector checks robots.txt and stops immediately on access/rate-limit errors.
"""

import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Callable
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit

import httpx

from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport

DOUBAN_BASE_URL = "https://movie.douban.com"
TOP250_URL = f"{DOUBAN_BASE_URL}/top250"
ROBOTS_URL = f"{DOUBAN_BASE_URL}/robots.txt"
USER_AGENT = "MovieHubChartCollector/0.1 (self-hosted personal use)"
PAGE_SIZE = 25
PAGE_COUNT = 10
PAGE_MAX_BYTES = 2 * 1024 * 1024
REQUEST_DELAY_SECONDS = 2.0


class DoubanCollectionError(RuntimeError):
    """A safe, actionable error while collecting a public Douban chart."""


class _Top250PageParser(HTMLParser):
    """Extract the stable facts needed for a normalized Top 250 snapshot."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None
        self.div_depth = 0
        self.capture_stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "div":
            classes = (attributes.get("class") or "").split()
            if self.current is None and "item" in classes:
                self.current = {
                    "titles": [],
                    "poster": "",
                    "douban_id": "",
                    "rank": "",
                    "rating": "",
                    "rating_count": "",
                    "details": "",
                }
                self.div_depth = 1
            elif self.current is not None:
                self.div_depth += 1

        if self.current is None:
            return

        if tag == "a":
            href = attributes.get("href", "")
            match = re.search(r"/subject/([0-9]+)/", href)
            if match and not self.current["douban_id"]:
                self.current["douban_id"] = match.group(1)

        if tag == "img" and not self.current["poster"]:
            self.current["poster"] = (
                attributes.get("src")
                or attributes.get("data-src")
                or ""
            )

        if tag == "br":
            self.current["details"] = str(self.current["details"]) + "\n"

        field = None
        if tag == "em":
            field = "rank"
        elif tag == "p":
            field = "details"
        elif tag == "span":
            classes = (attributes.get("class") or "").split()
            if "title" in classes:
                titles = self.current["titles"]
                assert isinstance(titles, list)
                titles.append("")
                field = f"title_{len(titles) - 1}"
            elif "rating_num" in classes:
                field = "rating"
            elif "pl" in classes:
                field = "rating_count"

        if field:
            if field.startswith("title_"):
                self.current[field] = ""
            self.capture_stack.append((tag, field))

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        for _, field in self.capture_stack:
            self.current[field] = str(self.current.get(field, "")) + data

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return

        for index in range(len(self.capture_stack) - 1, -1, -1):
            if self.capture_stack[index][0] == tag:
                self.capture_stack.pop(index)
                break

        if tag == "div":
            self.div_depth -= 1
            if self.div_depth == 0:
                self._finish_item()

    def _finish_item(self) -> None:
        assert self.current is not None
        titles = self.current.get("titles", [])
        if isinstance(titles, list):
            self.current["title"] = titles[0].strip() if titles else ""
            self.current["original_title"] = (
                titles[1].strip() if len(titles) > 1 else ""
            )
        self.items.append(self.current)
        self.current = None
        self.div_depth = 0
        self.capture_stack.clear()


def _public_poster_url(value: str) -> str | None:
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or re.fullmatch(r"img[0-9]+\.doubanio\.com", host) is None
        or parsed.port not in (None, 443)
    ):
        return None
    return value


def parse_top250_page(html: str) -> list[ChartMovieImport]:
    """Parse one Top 250 HTML page into validated chart movie records."""
    parser = _Top250PageParser()
    parser.feed(html)
    parser.close()

    result: list[ChartMovieImport] = []
    for item in parser.items:
        douban_id = str(item.get("douban_id", "")).strip()
        title = str(item.get("title", "")).strip()
        rank_text = str(item.get("rank", "")).strip()
        if not douban_id or not title or not rank_text:
            raise DoubanCollectionError(
                "Top 250 page markup changed or an item is incomplete"
            )

        try:
            rank = int(rank_text)
        except ValueError as exc:
            raise DoubanCollectionError("Invalid rank in Top 250 page") from exc

        rating_text = str(item.get("rating", "")).strip()
        try:
            rating = float(rating_text) if rating_text else None
        except ValueError:
            rating = None

        count_match = re.search(r"([0-9,]+)", str(item.get("rating_count", "")))
        rating_count = (
            int(count_match.group(1).replace(",", ""))
            if count_match
            else None
        )

        details = str(item.get("details", ""))
        metadata_match = re.search(
            r"(?m)([0-9]{4})\s*/\s*([^/\n]+)\s*/\s*([^\n]+)",
            details,
        )
        year = int(metadata_match.group(1)) if metadata_match else None
        regions = (
            [
                value
                for value in re.split(r"[、,，\s]+", metadata_match.group(2).strip())
                if value
            ]
            if metadata_match
            else []
        )
        genres = (
            [
                value
                for value in re.split(r"[、,，\s]+", metadata_match.group(3).strip())
                if value
            ]
            if metadata_match
            else []
        )

        poster = _public_poster_url(str(item.get("poster", "")))
        result.append(
            ChartMovieImport(
                douban_id=douban_id,
                rank=rank,
                source_rating=rating,
                title=title,
                original_title=str(item.get("original_title", "")).strip() or None,
                year=year,
                rating=rating,
                rating_count=rating_count,
                type="movie",
                genres=genres,
                regions=regions,
                posters=[poster] if poster else [],
                douban_url=f"{DOUBAN_BASE_URL}/subject/{douban_id}/",
            )
        )

    return result


class DoubanTop250Collector:
    """Collect one Top 250 snapshot using conservative public-page requests."""

    def __init__(
        self,
        client=None,
        sleeper: Callable[[float], None] = time.sleep,
        request_delay: float = REQUEST_DELAY_SECONDS,
    ) -> None:
        if request_delay < REQUEST_DELAY_SECONDS:
            raise ValueError(
                f"Request delay must be at least {REQUEST_DELAY_SECONDS} seconds"
            )
        self.client = client
        self.sleeper = sleeper
        self.request_delay = request_delay

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

    def _check_robots(self, client) -> None:
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

        if not parser.can_fetch(USER_AGENT, TOP250_URL):
            raise DoubanCollectionError(
                "Douban robots.txt disallows Top 250 collection for MovieHub"
            )

    def collect(self, snapshot_date: date) -> ChartSnapshotImport:
        owns_client = self.client is None
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

        try:
            self._check_robots(client)
            movies: list[ChartMovieImport] = []

            for page_index in range(PAGE_COUNT):
                start = page_index * PAGE_SIZE
                url = f"{TOP250_URL}?start={start}"
                response = client.get(TOP250_URL, params={"start": start})
                html = self._check_response(response, url)
                page_movies = parse_top250_page(html)

                expected_ranks = list(
                    range(start + 1, start + PAGE_SIZE + 1)
                )
                actual_ranks = [movie.rank for movie in page_movies]
                if actual_ranks != expected_ranks:
                    raise DoubanCollectionError(
                        f"Unexpected Top 250 ranks at start={start}; "
                        "the page may be incomplete or its markup changed"
                    )

                movies.extend(page_movies)
                if page_index < PAGE_COUNT - 1:
                    self.sleeper(self.request_delay)

            if len({movie.douban_id for movie in movies}) != 250:
                raise DoubanCollectionError(
                    "Top 250 collection contained duplicate or missing movie IDs"
                )

            return ChartSnapshotImport(
                slug="top250",
                name="豆瓣电影 Top 250",
                source="douban",
                category="classic",
                description="豆瓣电影 Top 250",
                snapshot_date=snapshot_date,
                movies=movies,
            )
        finally:
            if owns_client:
                client.close()
