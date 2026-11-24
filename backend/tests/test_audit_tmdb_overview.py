from datetime import date
from types import SimpleNamespace

from app.adapters.tmdb_overview import OverviewLookup
from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport
from scripts.audit_tmdb_overview import build_report, load_snapshots


class StubClient:
    def lookup(self, item, language):
        if language == "zh-CN":
            return OverviewLookup(
                status="overview_available",
                media_type="movie",
                tmdb_id=278,
                match_method="exact_title_year",
                language=language,
                overview_length=42,
                overview_sha256="a" * 64,
                source_url="https://www.themoviedb.org/movie/278",
                candidate_count=1,
            )
        return OverviewLookup(
            status="no_overview",
            media_type="movie",
            tmdb_id=278,
            match_method="exact_title_year",
            language=language,
            source_url="https://www.themoviedb.org/movie/278",
            candidate_count=1,
        )


def test_dry_run_report_deduplicates_movies_and_never_contains_synopsis_text():
    snapshot = ChartSnapshotImport(
        slug="dry-run-chart",
        name="Dry run chart",
        source="test",
        category="general",
        snapshot_date=date(2026, 11, 24),
        movies=[
            ChartMovieImport(
                douban_id="12345",
                rank=1,
                title="肖申克的救赎",
                original_title="The Shawshank Redemption",
                year=1994,
            )
        ],
    )

    report = build_report(
        [snapshot, snapshot],
        StubClient(),
        ["zh-CN", "zh-TW"],
    )

    assert report["mode"] == "read_only_dry_run"
    assert report["movie_count"] == 1
    assert report["record_count"] == 2
    assert report["by_language"]["zh-CN"]["overview_available"] == 1
    assert report["by_language"]["zh-TW"]["no_overview"] == 1
    serialized = str(report)
    assert "一段真实的剧情简介文本" not in serialized

def test_load_snapshots_reads_nested_first_launch_artifact_layout(tmp_path):
    nested = tmp_path / "moviehub-first-launch"
    nested.mkdir()
    snapshot = ChartSnapshotImport(
        slug="nested-chart",
        name="Nested chart",
        source="test",
        category="general",
        snapshot_date=date(2026, 11, 24),
        movies=[
            ChartMovieImport(
                douban_id="54321",
                rank=1,
                title="Nested fixture",
                year=2020,
            )
        ],
    )
    (nested / "snapshot.json").write_text(
        snapshot.model_dump_json(),
        encoding="utf-8",
    )

    loaded = load_snapshots(tmp_path, "2026-11-24")
    assert len(loaded) == 1
    assert loaded[0].slug == "nested-chart"
