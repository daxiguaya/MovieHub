from datetime import date

from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport
from scripts.audit_first_launch_data import summarize_snapshots


def _snapshot(slug, entries):
    return ChartSnapshotImport(
        slug=slug,
        name=slug,
        source="douban",
        category={"top250": "classic", "popular": "popular", "high-rated": "rating"}[slug],
        period={"top250": None, "popular": "realtime", "high-rated": None}[slug],
        snapshot_date=date(2026, 11, 24),
        movies=entries,
    )


def _movie(douban_id, rank, **kwargs):
    return ChartMovieImport(
        douban_id=douban_id,
        rank=rank,
        title=f"Movie {douban_id}",
        **kwargs,
    )


def test_audit_reports_unique_movies_overlap_and_field_coverage():
    report = summarize_snapshots([
        _snapshot("top250", [
            _movie("100", 1, year=2020, rating=8.5, directors=["Director"]),
            _movie("200", 2, year=2021),
        ]),
        _snapshot("popular", [
            _movie("100", 1, rating=8.5, posters=["https://img.example/a.jpg"]),
            _movie("300", 2, actors=["Actor"], genres=["Drama"]),
        ]),
        _snapshot("high-rated", [
            _movie("400", 1, overview="Synopsis", regions=["China"]),
        ]),
    ])

    assert report["valid"] is True
    assert report["chart_count"] == 3
    assert report["chart_item_count"] == 5
    assert report["unique_movie_count"] == 4
    assert report["cross_chart_duplicate_occurrences"] == 1
    assert report["metadata_coverage"]["year"]["present"] == 2
    assert report["metadata_coverage"]["rating"]["present"] == 2
    assert report["metadata_coverage"]["posters"]["present"] == 1


def test_audit_fails_when_a_required_first_launch_chart_is_missing():
    report = summarize_snapshots([
        _snapshot("popular", [_movie("200", 1)]),
        _snapshot("high-rated", [_movie("300", 1)]),
    ])

    assert report["valid"] is False
    assert any("top250" in error for error in report["errors"])
