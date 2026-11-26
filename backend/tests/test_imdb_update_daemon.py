"""Tests for the mounted-config IMDb updater."""
import json
from datetime import date

import pytest

from scripts import imdb_update_daemon as updater


def test_config_is_reloaded_from_mounted_json(tmp_path, monkeypatch):
    config_path = tmp_path / "imdb-update.json"
    monkeypatch.setattr(updater, "CONFIG_PATH", config_path)
    assert updater.load_config()["enabled"] is False

    replacement = config_path.with_suffix(".tmp")
    replacement.write_text(json.dumps({
        "enabled": True,
        "run_at": "03:15",
        "timezone": "Asia/Singapore",
        "auto_apply": False,
    }), encoding="utf-8")
    replacement.replace(config_path)
    config = updater.load_config()
    assert config["enabled"] is True
    assert config["run_at"] == "03:15"


def test_rejects_invalid_schedule(tmp_path, monkeypatch):
    config_path = tmp_path / "imdb-update.json"
    config_path.write_text(json.dumps({"run_at": "25:99"}), encoding="utf-8")
    monkeypatch.setattr(updater, "CONFIG_PATH", config_path)
    with pytest.raises(ValueError, match="run_at"):
        updater.load_config()


def test_unchanged_etag_skips_download_and_marks_day_complete(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(updater, "STATE_PATH", state_path)
    monkeypatch.setattr(updater, "request_headers", lambda: {
        "etag": '"same-version"', "last_modified": "", "content_length": "123"
    })
    monkeypatch.setattr(updater, "download_snapshot", lambda: pytest.fail("must not download"))
    monkeypatch.setattr(updater, "get_db_path", lambda: tmp_path / "movies.db")
    (tmp_path / "imdb-ratings.sqlite3").write_bytes(b"present")
    state = {"dataset_fingerprint": '"same-version"', "last_result": {
        "status": "applied", "dry_run": {"full_index": {"indexed_titles": 1000000}}
    }}
    result = updater.run_update({}, state, date(2026, 11, 26))
    assert result["status"] == "unchanged_dataset"
    assert state["last_successful_date"] == "2026-11-26"
    assert json.loads(state_path.read_text())["last_successful_date"] == "2026-11-26"


def test_new_snapshot_runs_dry_run_without_auto_applying(tmp_path, monkeypatch):
    snapshot = tmp_path / "title.ratings.tsv.gz"
    snapshot.write_bytes(b"test")
    monkeypatch.setattr(updater, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(updater, "request_headers", lambda: {
        "etag": '"new-version"', "last_modified": "", "content_length": "4"
    })
    monkeypatch.setattr(updater, "download_snapshot", lambda: (snapshot, "sha256"))
    calls = []
    monkeypatch.setattr(updater, "import_imdb_ratings", lambda path, apply=False: (
        calls.append(("local", apply)) or {"valid": True, "matched": 12, "changed": 3}
    ))
    monkeypatch.setattr(updater, "import_imdb_rating_index", lambda path, apply=False, min_rows=100000: (
        calls.append(("index", apply)) or {"valid": True, "indexed_titles": 1500000}
    ))
    state = {}
    result = updater.run_update({"auto_apply": False, "min_matched": 1, "min_index_rows": 100}, state, date(2026, 11, 26))
    assert result["status"] == "dry_run_only"
    assert calls == [("local", False), ("index", False)]
    assert state["dataset_fingerprint"] == '"new-version"'



def test_enabling_auto_apply_applies_saved_dry_run_snapshot(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "imdb"
    snapshot_dir.mkdir()
    (snapshot_dir / "title.ratings.tsv.gz").write_bytes(b"snapshot")
    monkeypatch.setattr(updater, "IMPORT_DIR", snapshot_dir)
    monkeypatch.setattr(updater, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(updater, "request_headers", lambda: {
        "etag": '"known-version"', "last_modified": "", "content_length": "8"
    })
    calls = []
    def fake_import(path, apply=False, min_rows=100000):
        calls.append(apply)
        return {"valid": True, "matched": 12, "indexed_titles": 12, "changed": 2, "applied": apply}
    monkeypatch.setattr(updater, "import_imdb_ratings", fake_import)
    monkeypatch.setattr(updater, "import_imdb_rating_index", fake_import)
    monkeypatch.setattr(updater, "get_db_path", lambda: tmp_path / "movies.db")
    monkeypatch.setattr(updater, "prune_backups", lambda path, keep: None)
    state = {
        "dataset_fingerprint": '"known-version"',
        "last_result": {"status": "dry_run_only"},
    }
    result = updater.run_update(
        {"auto_apply": True, "min_matched": 10, "min_index_rows": 10, "backup_keep": 7},
        state,
        date(2026, 11, 27),
    )
    assert result["status"] == "applied"
    assert calls == [False, False, True, True]



def test_old_dry_run_state_builds_missing_full_index_without_new_etag(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "imdb-imports"
    snapshot_dir.mkdir()
    (snapshot_dir / "title.ratings.tsv.gz").write_bytes(b"cached snapshot")
    monkeypatch.setattr(updater, "IMPORT_DIR", snapshot_dir)
    monkeypatch.setattr(updater, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(updater, "get_db_path", lambda: tmp_path / "movies.db")
    monkeypatch.setattr(updater, "request_headers", lambda: {
        "etag": '"same-version"', "last_modified": "", "content_length": "123"
    })
    calls = []
    monkeypatch.setattr(updater, "import_imdb_ratings", lambda path, apply=False: (
        calls.append(("local", apply)) or {"valid": True, "matched": 263}
    ))
    monkeypatch.setattr(updater, "import_imdb_rating_index", lambda path, apply=False, min_rows=100000: (
        calls.append(("index", apply)) or {"valid": True, "indexed_titles": 1500000}
    ))
    state = {
        "dataset_fingerprint": '"same-version"',
        "last_result": {"status": "dry_run_only", "dry_run": {"matched": 263}},
    }
    result = updater.run_update(
        {"auto_apply": False, "min_matched": 10, "min_index_rows": 100000},
        state,
        date(2026, 11, 27),
    )
    assert result["status"] == "dry_run_only"
    assert result["dry_run"]["full_index"]["indexed_titles"] == 1500000
    assert calls == [("local", False), ("index", False)]



def test_updater_checks_configured_index_path_for_unchanged_etag(tmp_path, monkeypatch):
    custom_index = tmp_path / "custom" / "ratings-index.sqlite3"
    custom_index.parent.mkdir()
    custom_index.write_bytes(b"present")
    monkeypatch.setenv("IMDB_RATINGS_INDEX_PATH", str(custom_index))
    monkeypatch.setattr(updater, "request_headers", lambda: {
        "etag": '"same-version"', "last_modified": "", "content_length": "123"
    })
    monkeypatch.setattr(updater, "download_snapshot", lambda: pytest.fail("must not download"))
    monkeypatch.setattr(updater, "get_db_path", lambda: tmp_path / "movies.db")
    monkeypatch.setattr(updater, "STATE_PATH", tmp_path / "state.json")
    state = {
        "dataset_fingerprint": '"same-version"',
        "last_result": {"status": "applied", "dry_run": {"full_index": {"indexed_titles": 1000000}}},
    }

    result = updater.run_update({}, state, date(2026, 11, 27))

    assert result["status"] == "unchanged_dataset"
