#!/bin/sh
# Safe one-command MovieHub online-discovery rollout for the Synology production repo.
# Default mode is read-only preflight. --deploy updates MovieHub backend, IMDb updater,
# and frontend; Nginx Proxy Manager is never restarted by this script.
set -eu

EXPECTED_ROOT="/volume1/docker/moviehub"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
MODE=check
if [ "$#" -ge 1 ]; then MODE=$1; fi

if [ "$ROOT" != "$EXPECTED_ROOT" ]; then
  echo "[FAIL] Expected production repo at $EXPECTED_ROOT, got $ROOT" >&2
  exit 1
fi
case "$MODE" in
  check|--check) MODE=check ;;
  deploy|--deploy) MODE=deploy ;;
  *) echo "Usage: sh deploy/rollout_online_discovery.sh [--check|--deploy]" >&2; exit 2 ;;
esac

cd "$ROOT"
if [ "$(git branch --show-current)" != "main" ]; then
  echo "[FAIL] Production checkout must be on main; no branch switching is performed." >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "[FAIL] docker CLI unavailable" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[FAIL] host python3 unavailable" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[FAIL] Docker Compose v2 unavailable" >&2; exit 1; }
[ -f .env ] || { echo "[FAIL] Production .env is missing" >&2; exit 1; }

echo "[1/6] Fetching main and checking tracked-file safety..."
git fetch origin main
if ! git diff --cached --quiet HEAD -- .; then
  echo "[FAIL] Staged tracked changes exist; refusing to overwrite them." >&2
  git status --short >&2
  exit 1
fi
if ! git diff --quiet HEAD -- . ':(exclude)docker-compose.yml'; then
  echo "[FAIL] Unexpected tracked local edits exist outside docker-compose.yml." >&2
  git status --short >&2
  exit 1
fi
# Production may intentionally keep a local Compose override (for example,
# fixed NPM-network IPs). Preserve it, but stop if upstream itself changed
# docker-compose.yml since this checkout; that requires an explicit review.
if ! git diff --quiet HEAD origin/main -- docker-compose.yml; then
  echo "[FAIL] origin/main changed docker-compose.yml since this production checkout." >&2
  echo "Review the upstream Compose change against the production override before retrying." >&2
  exit 1
fi
if ! git merge-base --is-ancestor HEAD origin/main; then
  echo "[FAIL] Production HEAD is not a fast-forward ancestor of origin/main." >&2
  exit 1
fi

docker compose config --quiet
TOKEN_OK=$(docker compose config --format json | python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["moviehub"]["environment"]; print("yes" if len(str(e.get("TMDB_API_READ_TOKEN", ""))) >= 80 else "no")')
API_KEY_OK=$(docker compose config --format json | python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["moviehub"]["environment"]; print("yes" if len(str(e.get("MOVIEHUB_API_KEY", ""))) >= 32 else "no")')
XIAOYA_OK=$(docker compose config --format json | python3 -c 'import json,sys; from urllib.parse import urlsplit; e=json.load(sys.stdin)["services"]["moviehub"]["environment"]; u=str(e.get("MOVIEHUB_XIAOYA_SEARCH_URL_TEMPLATE", "")); p=urlsplit(u.replace("{query}", "test")); print("yes" if "{query}" in u and p.scheme in ("http", "https") and p.netloc else "no")')
[ "$TOKEN_OK" = "yes" ] || { echo "[FAIL] TMDB_API_READ_TOKEN is missing or unexpectedly short; value not displayed." >&2; exit 1; }
[ "$API_KEY_OK" = "yes" ] || { echo "[FAIL] MOVIEHUB_API_KEY is missing or too short; value not displayed." >&2; exit 1; }
[ "$XIAOYA_OK" = "yes" ] || { echo "[FAIL] Set MOVIEHUB_XIAOYA_SEARCH_URL_TEMPLATE in .env with a valid http(s) URL containing {query}." >&2; exit 1; }
docker network inspect nginx-proxy-manager_default >/dev/null 2>&1 || { echo "[FAIL] Required NPM Docker network is missing" >&2; exit 1; }

DATA_PATH=$(python3 -c 'from pathlib import Path; p={}; [p.update({k.strip():v.strip().strip(chr(34)).strip(chr(39))}) for line in Path(".env").read_text().splitlines() if "=" in line and not line.lstrip().startswith("#") for k,v in [line.split("=",1)]]; print(p.get("MOVIEHUB_DATA_PATH", "/volume1/docker/moviehub/data"))')
BACKUP_PATH=$(python3 -c 'from pathlib import Path; p={}; [p.update({k.strip():v.strip().strip(chr(34)).strip(chr(39))}) for line in Path(".env").read_text().splitlines() if "=" in line and not line.lstrip().startswith("#") for k,v in [line.split("=",1)]]; print(p.get("MOVIEHUB_BACKUP_PATH", "/volume1/docker/moviehub/backup"))')
IMDB_CONFIG_DIR=$(python3 -c 'from pathlib import Path; p={}; [p.update({k.strip():v.strip().strip(chr(34)).strip(chr(39))}) for line in Path(".env").read_text().splitlines() if "=" in line and not line.lstrip().startswith("#") for k,v in [line.split("=",1)]]; q=Path(p.get("MOVIEHUB_IMDB_CONFIG_DIR", "./config")); print((q if q.is_absolute() else Path.cwd()/q).resolve())')
IMDB_CONFIG_PATH="$IMDB_CONFIG_DIR/imdb-update.json"
IMDB_CONFIG_TEMPLATE="$ROOT/deploy/imdb-update.json.example"
[ -d "$IMDB_CONFIG_DIR" ] || { echo "[FAIL] IMDb config directory missing: $IMDB_CONFIG_DIR" >&2; exit 1; }
[ -f "$IMDB_CONFIG_PATH" ] || { echo "[FAIL] IMDb updater config missing: $IMDB_CONFIG_PATH" >&2; exit 1; }
[ -f "$IMDB_CONFIG_TEMPLATE" ] || { echo "[FAIL] Tracked IMDb config template missing: $IMDB_CONFIG_TEMPLATE" >&2; exit 1; }
python3 - "$IMDB_CONFIG_PATH" "$IMDB_CONFIG_TEMPLATE" <<'PY'
import json
import sys
from pathlib import Path

for filename in sys.argv[1:]:
    with open(filename, encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise SystemExit("IMDb updater config must be a JSON object: " + filename)
    if not isinstance(config.get("enabled"), bool) or not isinstance(config.get("auto_apply"), bool):
        raise SystemExit("IMDb updater enabled/auto_apply must be booleans: " + filename)
    hour, minute = (int(part) for part in config["run_at"].split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit("Invalid IMDb updater run_at: " + filename)
    zone = Path("/usr/share/zoneinfo") / str(config["timezone"])
    if not zone.is_file():
        raise SystemExit("Unknown IMDb updater timezone: " + filename)
    if int(config.get("min_matched", 10)) < 1 or int(config.get("min_index_rows", 100000)) < 1:
        raise SystemExit("Invalid IMDb updater quality thresholds: " + filename)
print("IMDb updater config and template are valid.")
PY
[ -d "$DATA_PATH" ] || { echo "[FAIL] MovieHub data directory missing: $DATA_PATH" >&2; exit 1; }
[ -f "$DATA_PATH/db/movies.db" ] || { echo "[FAIL] Production movies.db missing; refusing rollout" >&2; exit 1; }
[ -d "$BACKUP_PATH" ] || { echo "[FAIL] Backup directory missing: $BACKUP_PATH" >&2; exit 1; }
docker image inspect moviehub-backend:local >/dev/null 2>&1 || { echo "[FAIL] Current backend rollback image is missing" >&2; exit 1; }
docker image inspect moviehub-frontend:local >/dev/null 2>&1 || { echo "[FAIL] Current frontend rollback image is missing" >&2; exit 1; }

CURRENT=$(git rev-parse --short HEAD)
TARGET=$(git rev-parse --short origin/main)
echo "[OK] Current code: $CURRENT; target main: $TARGET"
echo "[OK] Compose valid; TMDB token and API key present (values hidden)."
echo "[OK] Existing data, backup directory, NPM network, rollback images, and IMDb config found."
echo "[OK] Deployment installs tracked IMDb config template; daily IMDb updates and quality-gated auto-apply are enabled at 00:00 Asia/Shanghai."

if [ "$MODE" = "check" ]; then
  echo "[CHECK ONLY] No files, databases, images, or containers were changed."
  echo "Run: sh deploy/rollout_online_discovery.sh --deploy"
  exit 0
fi

printf "This will fast-forward main, back up SQLite and IMDb config, migrate the database, ENABLE daily IMDb dataset updates and quality-gated automatic rating writes at 00:00 Asia/Shanghai, and recreate ONLY MovieHub backend, IMDb updater, and frontend. NPM gets a graceful reload, not a restart. Continue? [y/N] "
read ANSWER
[ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ] || { echo "Cancelled; nothing deployed."; exit 0; }

STAMP=$(date +%Y%m%d-%H%M%S)
ROLLBACK_BACKEND="moviehub-backend:pre-online-discovery-$STAMP"
ROLLBACK_FRONTEND="moviehub-frontend:pre-online-discovery-$STAMP"
ROLLBACK_NEEDED=0

echo "[2/6] Creating SQLite online backups (main DB and discovery DB if present)..."
python3 - "$DATA_PATH" "$BACKUP_PATH" "$STAMP" <<'PY'
import sqlite3
import sys
from pathlib import Path

data_dir, backup_root, stamp = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
backup_dir = backup_root / ("online-discovery-rollout-" + stamp)
backup_dir.mkdir(parents=True, exist_ok=False)
sources = [data_dir / "db" / "movies.db", data_dir / "cache" / "discovery.sqlite3"]
for source_path in sources:
    if not source_path.is_file():
        if source_path.name == "movies.db":
            raise SystemExit("Production movies.db disappeared before backup")
        print("Discovery cache DB not present yet; it will be created by the new backend.")
        continue
    destination = backup_dir / (source_path.stem + ".sqlite3")
    source = sqlite3.connect("file:" + str(source_path) + "?mode=ro", uri=True, timeout=60)
    target = sqlite3.connect(str(destination), timeout=60)
    try:
        source.backup(target)
        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("SQLite backup integrity_check failed: " + source_path.name)
    finally:
        target.close()
        source.close()
    print("Backed up " + source_path.name + " -> " + str(destination))
print("Backup directory: " + str(backup_dir))
PY
cp -p "$IMDB_CONFIG_PATH" "$BACKUP_PATH/online-discovery-rollout-$STAMP/imdb-update.json"
: > "$BACKUP_PATH/online-discovery-rollout-$STAMP/imdb-config-existed"
echo "Backed up current IMDb updater config."

echo "[3/6] Saving current images and fast-forwarding production checkout..."
docker tag moviehub-backend:local "$ROLLBACK_BACKEND"
docker tag moviehub-frontend:local "$ROLLBACK_FRONTEND"
# Keep the NAS-local Compose override unstaged and untouched. The preflight
# already verified that origin/main has no Compose change to merge over it.
git merge --ff-only origin/main

echo "[4/6] Building the MovieHub backend, IMDb updater, and frontend images..."
docker compose build moviehub moviehub-imdb-updater moviehub-web

echo "[5/6] Migrating the MovieHub database and updating its three containers..."
reload_npm_routes() {
  docker inspect nginx-proxy-manager >/dev/null 2>&1 || { echo "[FAIL] nginx-proxy-manager container is unavailable" >&2; return 1; }
  docker exec nginx-proxy-manager nginx -t
  docker exec nginx-proxy-manager nginx -s reload
}
rollback() {
  echo "[ROLLBACK] Restoring previous images, IMDb config, and pre-migration MovieHub databases..." >&2
  docker compose stop moviehub moviehub-imdb-updater || true
  if [ -f "$ROLLBACK_DB_BACKUP" ]; then
    python3 - "$ROLLBACK_DB_BACKUP" "$DATA_PATH/db/movies.db" <<'PY'
import sqlite3
import sys
from pathlib import Path

backup_path, database_path = Path(sys.argv[1]), Path(sys.argv[2])
source = sqlite3.connect("file:" + str(backup_path) + "?mode=ro", uri=True, timeout=60)
target = sqlite3.connect(str(database_path), timeout=60)
try:
    source.backup(target)
    target.commit()
    integrity = target.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        raise RuntimeError("Restored production database failed integrity_check")
finally:
    target.close()
    source.close()
print("Restored pre-migration database:", database_path)
PY
  else
    echo "[FAIL] Pre-migration database backup is missing: $ROLLBACK_DB_BACKUP" >&2
    return 1
  fi
  # Online favorites and provider responses live in a separate SQLite cache DB.
  # Restore it too; otherwise a failed rollout could lose favorites on rollback.
  if [ -f "$ROLLBACK_DISCOVERY_DB_BACKUP" ]; then
    python3 - "$ROLLBACK_DISCOVERY_DB_BACKUP" "$DATA_PATH/cache/discovery.sqlite3" <<'PY'
import sqlite3
import sys
from pathlib import Path

backup_path, database_path = Path(sys.argv[1]), Path(sys.argv[2])
database_path.parent.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-wal", "-shm"):
    candidate = Path(str(database_path) + suffix)
    if candidate.exists():
        candidate.unlink()
source = sqlite3.connect("file:" + str(backup_path) + "?mode=ro", uri=True, timeout=60)
target = sqlite3.connect(str(database_path), timeout=60)
try:
    source.backup(target)
    target.commit()
    integrity = target.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        raise RuntimeError("Restored discovery cache failed integrity_check")
finally:
    target.close()
    source.close()
print("Restored pre-rollout discovery cache (including external favorites):", database_path)
PY
  else
    # No cache DB existed before rollout; discard any one created by the failed version.
    rm -f "$DATA_PATH/cache/discovery.sqlite3" "$DATA_PATH/cache/discovery.sqlite3-wal" "$DATA_PATH/cache/discovery.sqlite3-shm"
    echo "No discovery cache existed before rollout; removed failed-version cache files."
  fi
  cp -p "$ROLLBACK_CONFIG_BACKUP" "$IMDB_CONFIG_PATH"
  echo "Restored pre-rollout IMDb updater config."
  docker tag "$ROLLBACK_BACKEND" moviehub-backend:local
  docker tag "$ROLLBACK_FRONTEND" moviehub-frontend:local
  docker compose up -d --no-deps moviehub moviehub-imdb-updater moviehub-web || true
  # Container IPs may have changed again during rollback; refresh Nginx workers too.
  reload_npm_routes || echo "[WARN] NPM route reload failed after rollback; inspect NPM before retrying." >&2
}
on_exit() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$ROLLBACK_NEEDED" -eq 1 ]; then rollback; fi
  exit "$status"
}
trap on_exit EXIT

ROLLBACK_DB_BACKUP="$BACKUP_PATH/online-discovery-rollout-$STAMP/movies.sqlite3"
ROLLBACK_DISCOVERY_DB_BACKUP="$BACKUP_PATH/online-discovery-rollout-$STAMP/discovery.sqlite3"
ROLLBACK_CONFIG_BACKUP="$BACKUP_PATH/online-discovery-rollout-$STAMP/imdb-update.json"
ROLLBACK_NEEDED=1
docker compose stop moviehub moviehub-imdb-updater
docker compose run --rm --no-deps -T --name "moviehub-schema-migrate-$STAMP" moviehub python -m scripts.migrate
install -m 0644 "$IMDB_CONFIG_TEMPLATE" "$IMDB_CONFIG_PATH"
docker compose up -d --no-deps moviehub moviehub-imdb-updater moviehub-web

wait_healthy() {
  name="$1"
  attempt=0
  while [ "$attempt" -lt 50 ]; do
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)
    if [ "$state" = "healthy" ]; then return 0; fi
    attempt=$((attempt + 1))
    sleep 2
  done
  echo "[FAIL] $name did not become healthy" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}

wait_healthy moviehub-backend
wait_healthy moviehub-web

wait_running() {
  name="$1"
  attempt=0
  while [ "$attempt" -lt 25 ]; do
    state=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)
    if [ "$state" = "running" ]; then return 0; fi
    attempt=$((attempt + 1))
    sleep 2
  done
  echo "[FAIL] $name did not enter running state" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}
wait_running moviehub-imdb-updater

docker exec moviehub-imdb-updater python - <<'PY'
from scripts.imdb_update_daemon import load_config
config = load_config()
assert config["enabled"] is True, "IMDb scheduler must be enabled"
assert config["auto_apply"] is True, "IMDb auto-apply must be enabled"
assert config["run_at"] == "00:00"
assert config["timezone"] == "Asia/Shanghai"
assert config["min_index_rows"] == 100000
print("IMDb updater config verified: daily schedule and quality-gated auto-apply enabled, Asia/Shanghai 00:00.")
PY

# NPM caches static proxy_pass hostname resolution until its workers reload.
# This is a graceful Nginx reload, not an NPM container restart.
echo "[INFO] Refreshing NPM upstream DNS after MovieHub container recreation..."
reload_npm_routes

echo "[6/6] Running live API, cache, favorite-auth, and frontend smoke tests..."
docker exec moviehub-backend python - <<'PY'
import json
import os
import sqlite3
import urllib.request

base = "http://127.0.0.1:8000"
def get(path, headers=None):
    request = urllib.request.Request(base + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.loads(response.read().decode("utf-8"))

for path in ("/api/health", "/api/ready"):
    status, payload = get(path)
    assert status == 200, (path, status)
    print(path, "HTTP", status)

status, config = get("/api/config")
assert status == 200 and set(config) == {"xiaoyaSearchUrlTemplate"}, "Public runtime config API failed"
print("/api/config HTTP 200; Xiaoya template configured:", bool(config["xiaoyaSearchUrlTemplate"]))

status, regions = get("/api/discovery/regions")
assert status == 200 and isinstance(regions.get("regions"), list), "TMDB regions API failed"
print("/api/discovery/regions HTTP 200; regions:", len(regions["regions"]))

status, search = get("/api/discovery/search?q=Alien&page=1")
assert status == 200 and len(search.get("items", [])) <= 20, "TMDB search failed or page exceeded 20 items"
print("/api/discovery/search HTTP 200; current page items:", len(search["items"]))

status, stats = get("/api/discovery/cache-stats")
assert status == 200 and stats["entries"] <= 1500 and stats["bytes"] <= 32 * 1024 * 1024, "Cache hard limit violated"
print("/api/discovery/cache-stats HTTP 200; entries:", stats["entries"], "bytes:", stats["bytes"])

api_key = os.environ.get("MOVIEHUB_API_KEY", "")
status, favorites = get("/api/favorites/external", {"X-API-Key": api_key})
assert status == 200 and isinstance(favorites, list), "Unified authenticated external favorites API failed"
print("/api/favorites/external HTTP 200; favorites:", len(favorites))

db_path = os.path.join(os.environ.get("MOVIEHUB_DATA_DIR", "/data"), "cache", "discovery.sqlite3")
connection = sqlite3.connect(db_path)
try:
    bad = connection.execute("SELECT COUNT(*) FROM provider_response_cache WHERE response_json LIKE '%\"overview\"%'").fetchone()[0]
    assert bad == 0, "Unapproved overview text found in provider cache"
finally:
    connection.close()
print("Synopsis persistence check: 0 overview fields")
PY

docker exec moviehub-web wget -q -O /dev/null http://127.0.0.1:8080/
docker exec moviehub-web wget -q -O /dev/null http://moviehub:8000/api/health
# Verify the public path through NPM after the graceful reload; no NPM restart occurs.
PAGE_STATUS=$(docker exec nginx-proxy-manager sh -lc 'curl -kfsS --connect-timeout 5 --resolve zwnas.notedream.com:443:127.0.0.1 -o /dev/null -w "%{http_code}" https://zwnas.notedream.com/moviehub/')
API_STATUS=$(docker exec nginx-proxy-manager sh -lc 'curl -kfsS --connect-timeout 5 --resolve zwnas.notedream.com:443:127.0.0.1 -o /dev/null -w "%{http_code}" https://zwnas.notedream.com/moviehub/api/ready')
[ "$PAGE_STATUS" = "200" ] || { echo "[FAIL] NPM MovieHub page returned HTTP $PAGE_STATUS" >&2; exit 1; }
[ "$API_STATUS" = "200" ] || { echo "[FAIL] NPM MovieHub readiness returned HTTP $API_STATUS" >&2; exit 1; }
HEADERS=$(docker exec moviehub-web wget -S -O /dev/null http://127.0.0.1:8080/ 2>&1 || true)
echo "$HEADERS" | grep -F "img-src 'self' data: https://image.tmdb.org https://www.themoviedb.org" >/dev/null || { echo "[FAIL] Frontend CSP does not include TMDB image hosts" >&2; exit 1; }

ROLLBACK_NEEDED=0
trap - EXIT
echo "[SUCCESS] MovieHub is deployed and passed live smoke tests."
echo "Rollback image tags retained: $ROLLBACK_BACKEND and $ROLLBACK_FRONTEND"
echo "moviehub-backend, moviehub-imdb-updater, and moviehub-web were recreated. NPM received a graceful Nginx reload; its container was not restarted."
echo "SQLite backups retained under: $BACKUP_PATH/online-discovery-rollout-$STAMP"
