"""Preflight validation for built-in chart snapshot taxonomy."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas_chart_import import ChartSnapshotImport


def _payload(slug, category="annual", period="2025", media_type="movie"):
    return {
        "slug": slug,
        "name": "Fixture annual chart",
        "source": "douban",
        "category": category,
        "period": period,
        "snapshot_date": date(2026, 11, 23),
        "movies": [{
            "douban_id": "123456",
            "rank": 1,
            "title": "Fixture",
            "type": media_type,
        }],
    }


@pytest.mark.parametrize(
    "payload",
    [
        _payload("annual-2025-chinese-movies", category="popular"),
        _payload("annual-2025-chinese-movies", period="2026"),
        _payload("annual-2025-chinese-movies", media_type="tv"),
        _payload("annual-2025-chinese-tv", media_type="movie"),
    ],
)
def test_builtin_chart_taxonomy_mismatch_is_rejected_before_database_access(payload):
    with pytest.raises(ValidationError):
        ChartSnapshotImport.model_validate(payload)


def test_annual_chinese_tv_accepts_tv_entries():
    snapshot = ChartSnapshotImport.model_validate(
        _payload("annual-2025-chinese-tv", media_type="tv")
    )
    assert snapshot.movies[0].type == "tv"


def test_non_builtin_chart_slug_keeps_generic_import_behavior():
    snapshot = ChartSnapshotImport.model_validate({
        "slug": "operator-custom-chart",
        "name": "Custom chart",
        "source": "local",
        "category": "general",
        "snapshot_date": date(2026, 11, 23),
        "movies": [{
            "douban_id": "123456",
            "rank": 1,
            "title": "Fixture",
            "type": "tv",
        }],
    })
    assert snapshot.slug == "operator-custom-chart"
