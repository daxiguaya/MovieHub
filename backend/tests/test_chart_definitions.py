"""Tests for the initial built-in chart catalogue."""

from app.chart_definitions import INITIAL_CHARTS, get_chart_definition


def test_builtin_chart_slugs_are_unique():
    slugs = [chart.slug for chart in INITIAL_CHARTS]
    assert len(slugs) == len(set(slugs))


def test_2025_annual_lists_match_the_official_chart_categories():
    annual_2025 = {
        chart.slug: chart
        for chart in INITIAL_CHARTS
        if chart.category == "annual" and chart.period == "2025"
    }

    assert set(annual_2025) == {
        "annual-2025-chinese-movies",
        "annual-2025-international-movies",
        "annual-2025-hidden-gems",
        "annual-2025-chinese-tv",
    }
    assert annual_2025["annual-2025-chinese-movies"].name == "2025 评分最高华语电影"
    assert annual_2025["annual-2025-international-movies"].name == "2025 评分最高外语电影"
    assert annual_2025["annual-2025-hidden-gems"].name == "2025 年度冷门佳片"
    assert annual_2025["annual-2025-chinese-tv"].name == "2025 评分最高华语剧集"
    assert all(chart.source == "douban" for chart in annual_2025.values())


def test_unpublished_2026_annual_chart_is_not_exposed_as_an_empty_placeholder():
    assert get_chart_definition("annual-2026") is None


def test_annual_tv_definition_declares_tv_media_type():
    assert get_chart_definition("annual-2025-chinese-tv").media_type == "tv"


def test_annual_movie_definitions_declare_movie_media_type():
    for slug in (
        "annual-2025-chinese-movies",
        "annual-2025-international-movies",
        "annual-2025-hidden-gems",
    ):
        assert get_chart_definition(slug).media_type == "movie"
