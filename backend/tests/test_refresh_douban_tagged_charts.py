from datetime import date
from types import SimpleNamespace

import pytest

from scripts import refresh_douban_tagged_charts as refresh


def test_collects_popular_and_high_rated_before_import(monkeypatch):
    calls = []

    class FakeCollector:
        def __init__(self, max_items):
            assert max_items == 75

        def collect(self, chart_key, snapshot_date):
            calls.append((chart_key, snapshot_date))
            return SimpleNamespace(
                slug=chart_key,
                movies=[object(), object()],
            )

    monkeypatch.setattr(refresh, "DoubanTaggedChartCollector", FakeCollector)

    snapshots = refresh.collect_snapshots(
        date(2026, 11, 25),
        max_items=75,
    )

    assert [snapshot.slug for snapshot in snapshots] == [
        "popular",
        "high-rated",
    ]
    assert [len(snapshot.movies) for snapshot in snapshots] == [2, 2]
    assert calls == [
        ("popular", date(2026, 11, 25)),
        ("high-rated", date(2026, 11, 25)),
    ]


def test_collection_failure_stops_batch_before_any_import(monkeypatch):
    calls = []

    class FakeCollector:
        def __init__(self, max_items):
            pass

        def collect(self, chart_key, snapshot_date):
            calls.append(chart_key)
            raise RuntimeError("Douban returned HTTP 403")

    monkeypatch.setattr(refresh, "DoubanTaggedChartCollector", FakeCollector)

    with pytest.raises(RuntimeError, match="HTTP 403"):
        refresh.collect_snapshots(date(2026, 11, 25))

    # The second chart is not requested after access is denied.
    assert calls == ["popular"]


def test_rejects_unknown_chart_before_collection(monkeypatch):
    class FakeCollector:
        def __init__(self, max_items):
            pass

        def collect(self, chart_key, snapshot_date):
            pytest.fail("collector must not be called for an unknown chart")

    monkeypatch.setattr(refresh, "DoubanTaggedChartCollector", FakeCollector)

    with pytest.raises(ValueError, match="Unsupported Douban chart"):
        refresh.collect_snapshots(
            date(2026, 11, 25),
            chart_keys=("not-a-chart",),
        )
