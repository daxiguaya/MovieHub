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

CONFIG_PATH = Path(os.environ.get("IMDB_UPDATE_CONFIG", "/config/imdb-update.json"))
STATE_PATH = Path(os.environ.get("IMDB_UPDATE_STATE", "/state/state.json"))
IMPORT_DIR = Path(os.environ.get("IMDB_UPDATE_IMPORT_DIR", "/imports/imdb"))
LOG = logging.getLogger("moviehub.imdb_update")


def load_config() -> dict:
    defaults = {
        "enabled": False,
        "run_at": "04:30",
        "timezone": "Asia/Singapore",
        "auto_apply": False,
        "min_matched": 1,
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
    if int(config["min_matched"]) < 1 or int(config["backup_keep"]) < 1:
        raise ValueError("min_matched and backup_keep must be positive")
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


def run_update(config: dict, state: dict, today: date) -> dict:
    headers = request_headers()
    fingerprint = headers["etag"] or headers["last_modified"]
    previous = state.get("dataset_fingerprint")
    if fingerprint and fingerprint == previous:
        result = {"status": "unchanged_dataset", "checked_at": datetime.now().astimezone().isoformat()}
        state["last_result"] = result
        state["last_successful_date"] = today.isoformat()
        state["last_success_at"] = datetime.now().astimezone().isoformat()
        write_state(state)
        return result

    snapshot, content_hash = download_snapshot()
    if not fingerprint and content_hash == previous:
        result = {"status": "unchanged_dataset", "sha256": content_hash}
        state["last_result"] = result
        state["last_successful_date"] = today.isoformat()
        state["last_success_at"] = datetime.now().astimezone().isoformat()
        write_state(state)
        return result
    dry_run = import_imdb_ratings(snapshot, apply=False)
    if not dry_run.get("valid") or int(dry_run.get("matched", 0)) < int(config["min_matched"]):
        raise RuntimeError(f"IMDb dry-run quality gate failed: {dry_run}")
    result = {"status": "dry_run_only", "dry_run": dry_run}
    if config["auto_apply"]:
        applied = import_imdb_ratings(snapshot, apply=True)
        result = {"status": "applied", "dry_run": dry_run, "applied_result": applied}
        prune_backups(Path(get_db_path()).resolve(), int(config["backup_keep"]))

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
