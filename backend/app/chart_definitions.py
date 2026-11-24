"""Initial MovieHub chart definitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartDefinition:
    slug: str
    name: str
    source: str
    category: str
    period: str | None
    description: str
    display_order: int
    media_type: str = "movie"


INITIAL_CHARTS: tuple[ChartDefinition, ...] = (
    ChartDefinition(
        slug="top250",
        name="豆瓣电影 Top 250",
        source="douban",
        category="classic",
        period=None,
        description="豆瓣电影 Top 250 经典电影榜单",
        display_order=10,
    ),
    ChartDefinition(
        slug="popular",
        name="豆瓣实时热门",
        source="douban",
        category="popular",
        period="realtime",
        description="实时热门电影发现榜单",
        display_order=20,
    ),
    ChartDefinition(
        slug="high-rated",
        name="豆瓣高分电影",
        source="douban",
        category="rating",
        period=None,
        description="按评分和评价人数筛选的高分电影榜单",
        display_order=30,
    ),
    ChartDefinition(
        slug="annual-2025-chinese-movies",
        name="2025 评分最高华语电影",
        source="douban",
        category="annual",
        period="2025",
        description="豆瓣 2025 年度华语电影榜单",
        display_order=40,
    ),
    ChartDefinition(
        slug="annual-2025-international-movies",
        name="2025 评分最高外语电影",
        source="douban",
        category="annual",
        period="2025",
        description="豆瓣 2025 年度外语电影榜单",
        display_order=50,
    ),
    ChartDefinition(
        slug="annual-2025-hidden-gems",
        name="2025 年度冷门佳片",
        source="douban",
        category="annual",
        period="2025",
        description="豆瓣 2025 年度冷门佳片榜单",
        display_order=60,
    ),
    ChartDefinition(
        slug="annual-2025-chinese-tv",
        name="2025 评分最高华语剧集",
        source="douban",
        category="annual",
        period="2025",
        description="豆瓣 2025 年度华语剧集榜单",
        display_order=70,
        media_type="tv",
    ),
)


def get_chart_definition(slug: str) -> ChartDefinition | None:
    """Find an initial chart definition by its stable slug."""
    return next(
        (chart for chart in INITIAL_CHARTS if chart.slug == slug),
        None,
    )
