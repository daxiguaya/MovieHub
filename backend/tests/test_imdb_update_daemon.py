"""Tests for the mounted-config IMDb updater."""
import json
from datetime import date

import pytest

from scripts import imdb_update_daemon as updater


def test_config_is_reloaded_from_mounted_json(tmp_path, monkeypatch):
    config_path = tmp_path / "imdb-update.json"
    monkeypatch.setattr(updater, "CONFIG_PATH", config_path)
    assert updater.load_config()["enabled"] is False

    config_path.write_text(json.dumps({
        "enabled": True,
        "run_at": "03:15",
        "timezone": "Asia/Singapore",
        "auto_apply": False,
    }), encoding="utf-8")
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
    state = {"dataset_fingerprint": '"same-version"'}
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
        calls.append(apply) or {"valid": True, "matched": 12, "changed": 3}
    ))
    state = {}
    result = updater.run_update({"auto_apply": False, "min_matched": 1}, state, date(2026, 11, 26))
    assert result["status"] == "dry_run_only"
    assert calls == [False]
    assert state["dataset_fingerprint"] == '"new-version"'
