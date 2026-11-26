"""Daily, private IMDb ratings updater controlled by a mounted JSON file.

The daemon checks the official dataset only at the configured local time.
It downloads a complete snapshot only when the HTTP validator changes, verifies
gzip integrity, runs the importer in dry-run mode, and optionally applies it.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import logging
import os
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.database import get_db_path
from scripts.import_imdb_ratings import IMDB_RATINGS_URL, import_imdb_ratings
from scripts.import_imdb_rating_index import import_imdb_rating_index

CONFIG_PATH = Path(os.environ.get("IMDB_UPDATE_CONFIG", "/config/imdb-update.json"))
STATE_PATH = Path(os.environ.get("IMDB_UPDATE_STATE", "/state/state.json"))
IMPORT_DIR = Path(os.environ.get("IMDB_UPDATE_IMPORT_DIR", "/data/imdb-imports"))
LOG = logging.getLogger("moviehub.imdb_update")


def load_config() -> dict:
    defaults = {
        "enabled": False,
        "run_at": "04:30",
        "timezone": "Asia/Singapore",
        "auto_apply": False,
        "min_matched": 10,
        "min_index_rows": 100000,
        "backup_keep": 7,
        "retry_minutes": 15,
    }
    if not CONFIG_PATH.is_file():
        return defaults
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("IMDb update config must be a JSON object")
    config = {**defaults, **raw}
    if not isinstance(config["enabled"], bool) or not isinstance(config["auto_apply"], bool):
        raise ValueError("enabled and auto_apply must be JSON booleans")
    hour, minute = (int(part) for part in config["run_at"].split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("run_at must use HH:MM")
    ZoneInfo(config["timezone"])
    if int(config["min_matched"]) < 1 or int(config["min_index_rows"]) < 1 or int(config["backup_keep"]) < 1:
        raise ValueError("min_matched, min_index_rows and backup_keep must be positive")
    return config


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        LOG.exception("Could not read updater state; starting with empty state")
        return {}


def write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def request_headers() -> dict[str, str]:
    request = urllib.request.Request(IMDB_RATINGS_URL, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return {
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "content_length": response.headers.get("Content-Length", ""),
        }


def download_snapshot() -> tuple[Path, str]:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = IMPORT_DIR / "title.ratings.tsv.gz.part"
    final_path = IMPORT_DIR / "title.ratings.tsv.gz"
    digest = hashlib.sha256()
    request = urllib.request.Request(IMDB_RATINGS_URL)
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        # Read the entire gzip stream: this catches truncated/corrupt downloads.
        with gzip.open(temporary, "rb") as source:
            while source.read(4 * 1024 * 1024):
                pass
        os.replace(temporary, final_path)
        return final_path, digest.hexdigest()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def prune_backups(database_path: Path, keep: int) -> None:
    pattern = f"{database_path.stem}.pre-imdb-ratings-*.sqlite3"
    backups = sorted(database_path.parent.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        stale.unlink(missing_ok=True)


def prune_index_backups(index_path: Path, keep: int) -> None:
    pattern = f"{index_path.stem}.pre-full-imdb-index-*.sqlite3"
    backups = sorted(index_path.parent.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        stale.unlink(missing_ok=True)


def run_update(config: dict, state: dict, today: date) -> dict:
    headers = request_headers()
    fingerprint = headers["etag"] or headers["last_modified"]
    previous = state.get("dataset_fingerprint")
    if fingerprint and fingerprint == previous:
        previous_result = state.get("last_result", {})
        saved_snapshot = IMPORT_DIR / "title.ratings.tsv.gz"
        previous_dry_run = previous_result.get("dry_run") or {}
        index_path = Path(get_db_path()).resolve().with_name("imdb-ratings.sqlite3")
        # Older updater state only records the local catalogue import. Ensure
        # the complete index is built even when IMDb's ETag has not changed.
        needs_full_index = not index_path.is_file() or "full_index" not in previous_dry_run
        needs_apply = config.get("auto_apply") and previous_result.get("status") == "dry_run_only"
        if needs_full_index or needs_apply:
            if not saved_snapshot.is_file():
                saved_snapshot, saved_hash = download_snapshot()
                state["dataset_sha256"] = saved_hash
            local_dry_run = import_imdb_ratings(saved_snapshot, apply=False)
            index_dry_run = import_imdb_rating_index(saved_snapshot, apply=False, min_rows=int(config["min_index_rows"]))
            if not local_dry_run.get("valid") or int(local_dry_run.get("matched", 0)) < int(config["min_matched"]):
                raise RuntimeError(f"Local IMDb ratings quality gate failed before apply: {local_dry_run}")
            if not index_dry_run.get("valid") or int(index_dry_run.get("indexed_titles", 0)) < int(config["min_index_rows"]):
                raise RuntimeError(f"Full IMDb index quality gate failed before apply: {index_dry_run}")
            dry_run = {"local": local_dry_run, "full_index": index_dry_run}
            if config.get("auto_apply"):
                applied_index = import_imdb_rating_index(saved_snapshot, apply=True, min_rows=int(config["min_index_rows"]))
                applied_local = import_imdb_ratings(saved_snapshot, apply=True)
                prune_backups(Path(get_db_path()).resolve(), int(config["backup_keep"]))
                prune_index_backups(index_path, int(config["backup_keep"]))
                result = {"status": "applied", "dry_run": dry_run, "applied_result": {"local": applied_local, "full_index": applied_index}}
            else:
                result = {"status": "dry_run_only", "dataset_unchanged": True, "dry_run": dry_run}
        elif previous_result.get("status") == "dry_run_only":
            result = {
                "status": "dry_run_only",
                "dataset_unchanged": True,
                "dry_run": previous_result.get("dry_run"),
            }
        else:
            result = {"status": "unchanged_dataset", "checked_at": datetime.now().astimezone().isoformat()}
        state["last_result"] = result
        state["last_successful_date"] = today.isoformat()
        state["last_success_at"] = datetime.now().astimezone().isoformat()
        write_state(state)
        return result

    snapshot, content_hash = download_snapshot()
    index_path = Path(get_db_path()).resolve().with_name("imdb-ratings.sqlite3")
    previous_dry_run = (state.get("last_result") or {}).get("dry_run") or {}
    if not fingerprint and content_hash == previous and index_path.is_file() and "full_index" in previous_dry_run:
        result = {"status": "unchanged_dataset", "sha256": content_hash}
        state["last_result"] = result
        state["last_successful_date"] = today.isoformat()
        state["last_success_at"] = datetime.now().astimezone().isoformat()
        write_state(state)
        return result
    local_dry_run = import_imdb_ratings(snapshot, apply=False)
    index_dry_run = import_imdb_rating_index(snapshot, apply=False, min_rows=int(config["min_index_rows"]))
    if not local_dry_run.get("valid") or int(local_dry_run.get("matched", 0)) < int(config["min_matched"]):
        raise RuntimeError(f"Local IMDb ratings quality gate failed: {local_dry_run}")
    if not index_dry_run.get("valid") or int(index_dry_run.get("indexed_titles", 0)) < int(config["min_index_rows"]):
        raise RuntimeError(f"Full IMDb index quality gate failed: {index_dry_run}")
    dry_run = {"local": local_dry_run, "full_index": index_dry_run}
    result = {"status": "dry_run_only", "dry_run": dry_run}
    if config["auto_apply"]:
        applied_index = import_imdb_rating_index(snapshot, apply=True, min_rows=int(config["min_index_rows"]))
        applied_local = import_imdb_ratings(snapshot, apply=True)
        result = {"status": "applied", "dry_run": dry_run, "applied_result": {"local": applied_local, "full_index": applied_index}}
        prune_backups(Path(get_db_path()).resolve(), int(config["backup_keep"]))
        prune_index_backups(Path(get_db_path()).resolve().with_name("imdb-ratings.sqlite3"), int(config["backup_keep"]))

    state["dataset_fingerprint"] = fingerprint or content_hash
    state["dataset_sha256"] = content_hash
    state["last_successful_date"] = today.isoformat()
    state["last_result"] = result
    state["last_success_at"] = datetime.now().astimezone().isoformat()
    write_state(state)
    return result


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("IMDb updater started; config=%s", CONFIG_PATH)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = (STATE_PATH.parent / "updater.lock").open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        LOG.error("Another IMDb updater process already holds the state lock; exiting")
        return
    attempted: dict[str, float] = {}
    while True:
        try:
            config = load_config()  # Reload every loop; mounted file edits need no container recreation.
            if not config["enabled"]:
                time.sleep(30)
                continue
            now = datetime.now(ZoneInfo(config["timezone"]))
            hour, minute = (int(part) for part in config["run_at"].split(":"))
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            key = now.date().isoformat()
            state = read_state()
            last_date = state.get("last_successful_date")
            last_attempt = attempted.get(key, 0)
            retry_seconds = max(1, int(config["retry_minutes"])) * 60
            if now >= scheduled and last_date != key and time.time() - last_attempt >= retry_seconds:
                attempted[key] = time.time()
                LOG.info("Starting scheduled IMDb dataset check for %s", key)
                result = run_update(config, state, now.date())
                LOG.info("IMDb update result: %s", json.dumps(result, ensure_ascii=False))
        except Exception:
            LOG.exception("IMDb scheduled update failed; will retry")
        time.sleep(30)


if __name__ == "__main__":
    main()
