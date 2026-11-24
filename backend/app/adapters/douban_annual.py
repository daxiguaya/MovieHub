"""Conservative one-shot collector for Douban's official 2025 annual roundup.

The official blog article is the source of ranking membership, rank, title,
director and source rating. This is not a supported API. Collection is opt-in,
checks the blog host's robots.txt, uses no cookies/proxies/retries, rejects
redirects and fails closed when access is denied or markup changes.
"""
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.adapters.douban_top250 import (
    PAGE_MAX_BYTES,
    USER_AGENT,
    DoubanCollectionError,
)
from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport

ANNUAL_SOURCE_URL = "https://blog.douban.com/douban/2026/01/15/4382/"
ANNUAL_ROBOTS_URL = "https://blog.douban.com/robots.txt"
MAX_PAGE_BYTES = 2 * 1024 * 1024
REQUEST_DELAY_SECONDS = 2.0

ANNUAL_CHARTS = {
    "annual-2025-chinese-movies": {
        "name": "2025 评分最高华语电影",
        "media_type": "movie",
        "description": "豆瓣官方 2025 年度评分最高华语电影榜单",
    },
    "annual-2025-international-movies": {
        "name": "2025 评分最高外语电影",
        "media_type": "movie",
        "description": "豆瓣官方 2025 年度评分最高外语电影榜单",
    },
    "annual-2025-hidden-gems": {
        "name": "2025 年度冷门佳片",
        "media_type": "movie",
        "description": "豆瓣官方 2025 年度冷门佳片榜单",
    },
    "annual-2025-chinese-tv": {
        "name": "2025 评分最高华语剧集",
        "media_type": "tv",
        "description": "豆瓣官方 2025 年度评分最高华语剧集榜单",
    },
}

_SECTION_ALIASES = {
    "2025评分最高的华语电影": "annual-2025-chinese-movies",
    "2025评分最高华语电影": "annual-2025-chinese-movies",
    "2025评分最高的外语电影": "annual-2025-international-movies",
    "2025评分最高外语电影": "annual-2025-international-movies",
    "2025年度冷门佳片": "annual-2025-hidden-gems",
    "2025评分最高华语剧集": "annual-2025-chinese-tv",
}


def _normalise_heading(value: str) -> str:
    return re.sub(r"[\s：:〖〗【】]", "", value)


class _AnnualArticleParser(HTMLParser):
    """Extract ranked linked rows while retaining the official section scope."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_slug: str | None = None
        self.rows: dict[str, list[dict[str, object]]] = {
            slug: [] for slug in ANNUAL_CHARTS
        }
        self.block_tag: str | None = None
        self.block_text: list[str] = []
        self.in_row = False
        self.cells: list[dict[str, object]] = []
        self.cell: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p"}:
            self.block_tag = tag
            self.block_text = []
        if tag == "tr":
            self.in_row = True
            self.cells = []
            self.cell = None
        elif self.in_row and tag in {"td", "th"}:
            self.cell = {"text": "", "hrefs": []}
            self.cells.append(self.cell)
        elif self.in_row and tag == "a" and self.cell is not None:
            href = attrs_dict.get("href") or ""
            hrefs = self.cell["hrefs"]
            assert isinstance(hrefs, list)
            hrefs.append(href)

    def handle_data(self, data: str) -> None:
        if self.block_tag is not None:
            self.block_text.append(data)
        if self.in_row and self.cell is not None:
            self.cell["text"] = str(self.cell["text"]) + data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p"} and tag == self.block_tag:
            heading = _normalise_heading("".join(self.block_text))
            self.current_slug = _SECTION_ALIASES.get(heading)
            self.block_tag = None
            self.block_text = []
        if self.in_row and tag in {"td", "th"}:
            self.cell = None
        elif self.in_row and tag == "tr":
            if self.current_slug:
                self.rows[self.current_slug].append(
                    {
                        "cells": self.cells,
                    }
                )
            self.in_row = False
            self.cells = []
            self.cell = None


def _subject_id(hrefs: list[str]) -> tuple[str, str] | None:
    for href in hrefs:
        try:
            candidate = href if "://" in href else f"https:{href}" if href.startswith("//") else ""
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == "movie.douban.com"
            and parsed.port in (None, 80, 443)
        ):
            match = re.fullmatch(r"/subject/([0-9]+)/?", parsed.path)
            if match:
                return match.group(1), f"https://movie.douban.com/subject/{match.group(1)}/"
    return None


def parse_annual_article(html: str, snapshot_date: date) -> dict[str, ChartSnapshotImport]:
    """Parse the official 2025 article into four independent normalized snapshots."""
    parser = _AnnualArticleParser()
    parser.feed(html)
    parser.close()

    snapshots: dict[str, ChartSnapshotImport] = {}
    for slug, config in ANNUAL_CHARTS.items():
        parsed_items: list[ChartMovieImport] = []
        seen_ids: set[str] = set()
        seen_ranks: set[int] = set()

        for row in parser.rows[slug]:
            cells = row["cells"]
            assert isinstance(cells, list)
            if len(cells) < 3:
                continue

            rank_match = re.search(r"([0-9]{1,2})", str(cells[0]["text"]))
            if not rank_match:
                continue
            rank = int(rank_match.group(1))
            if not 1 <= rank <= 10:
                raise DoubanCollectionError(f"Unexpected annual rank {rank} in {slug}")

            # Do not assume the linked title is always the second table cell:
            # Douban's WordPress markup may add an empty/auxiliary cell.
            subject_cell_index = None
            subject = None
            for cell_index, cell in enumerate(cells):
                hrefs = cell["hrefs"]
                assert isinstance(hrefs, list)
                candidate = _subject_id(hrefs)
                if candidate is not None:
                    subject_cell_index = cell_index
                    subject = candidate
                    break

            fallback_title = str(cells[1]["text"]).strip()
            # The official article explicitly uses "空缺" for unfilled ranks.
            if fallback_title == "空缺" and subject is None:
                continue
            if subject is None or subject_cell_index is None:
                href_summary = [href for cell in cells for href in cell["hrefs"]]
                raise DoubanCollectionError(
                    f"Annual chart {slug} rank {rank} ({fallback_title!r}) "
                    f"has no valid Douban subject link; hrefs={href_summary!r}"
                )

            title = str(cells[subject_cell_index]["text"]).strip()
            if not title:
                raise DoubanCollectionError(
                    f"Annual chart {slug} rank {rank} has an empty linked title"
                )

            douban_id, douban_url = subject
            if douban_id in seen_ids or rank in seen_ranks:
                raise DoubanCollectionError(f"Duplicate ID or rank in annual chart {slug}")

            other_cells = [
                str(cell["text"]).strip()
                for index, cell in enumerate(cells)
                if index not in {0, subject_cell_index}
            ]
            rating_index = next(
                (
                    index for index in range(len(other_cells) - 1, -1, -1)
                    if re.fullmatch(r"(?:[0-9]+\.)?[0-9]+", other_cells[index])
                ),
                None,
            )
            rating = float(other_cells[rating_index]) if rating_index is not None else None
            director_text = " ".join(
                value for index, value in enumerate(other_cells)
                if index != rating_index and value
            )
            directors = [
                value.strip()
                for value in re.split(r"\s*/\s*|\s+", director_text)
                if value.strip()
            ]

            parsed_items.append(
                ChartMovieImport(
                    douban_id=douban_id,
                    rank=rank,
                    source_rating=rating,
                    title=title,
                    rating=rating,
                    type=config["media_type"],
                    directors=directors,
                    douban_url=douban_url,
                )
            )
            seen_ids.add(douban_id)
            seen_ranks.add(rank)

        if not parsed_items:
            raise DoubanCollectionError(
                f"Official annual article did not yield entries for {slug}; markup may have changed"
            )

        snapshots[slug] = ChartSnapshotImport(
            slug=slug,
            name=config["name"],
            source="douban",
            category="annual",
            period="2025",
            description=config["description"],
            snapshot_date=snapshot_date,
            movies=sorted(parsed_items, key=lambda item: item.rank),
        )

    return snapshots


class DoubanAnnualChartCollector:
    """Fetch the official roundup once and return all four annual snapshots."""

    def __init__(
        self,
        client=None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.sleeper = sleeper

    @staticmethod
    def _check_response(response, url: str) -> str:
        if response.status_code in (401, 403, 429):
            raise DoubanCollectionError(
                f"Douban denied or rate-limited the request (HTTP {response.status_code}); no retry or bypass"
            )
        if 300 <= response.status_code < 400:
            raise DoubanCollectionError(f"Unexpected redirect while requesting {url}")
        if response.status_code != 200:
            raise DoubanCollectionError(
                f"Unexpected HTTP {response.status_code} while requesting {url}"
            )
        if len(response.content) > MAX_PAGE_BYTES:
            raise DoubanCollectionError("Official annual article exceeded the 2 MiB limit")
        return response.text

    @staticmethod
    def _check_robots(client) -> float:
        response = client.get(ANNUAL_ROBOTS_URL)
        if response.status_code == 404:
            parser = RobotFileParser()
            parser.parse([])
        elif response.status_code == 200:
            if len(response.content) > 256 * 1024:
                raise DoubanCollectionError("Douban blog robots.txt is unexpectedly large")
            parser = RobotFileParser()
            parser.set_url(ANNUAL_ROBOTS_URL)
            parser.parse(response.text.splitlines())
        else:
            raise DoubanCollectionError(
                f"Could not safely read Douban blog robots.txt (HTTP {response.status_code})"
            )
        if not parser.can_fetch(USER_AGENT, ANNUAL_SOURCE_URL):
            raise DoubanCollectionError(
                "Douban blog robots.txt disallows the official annual article"
            )
        return max(REQUEST_DELAY_SECONDS, float(parser.crawl_delay(USER_AGENT) or 0.0))

    def collect(self, snapshot_date: date) -> dict[str, ChartSnapshotImport]:
        owns_client = self.client is None
        client = self.client or httpx.Client(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        try:
            delay = self._check_robots(client)
            # robots.txt is a separate request to the same host; keep a small
            # conservative gap before fetching the article.
            self.sleeper(delay)
            html = self._check_response(
                client.get(ANNUAL_SOURCE_URL),
                ANNUAL_SOURCE_URL,
            )
            return parse_annual_article(html, snapshot_date)
        finally:
            if owns_client:
                client.close()
