# Backend container deployment (initial packaging)

This is a backend-only deployment package. The repository does not yet contain a finalized frontend, so this Compose file deliberately deploys only the API. It does not initialize a database, import Scout data, or expose a host port.

## Runtime layout

- API container: `moviehub-backend`, port 8000 on its Docker networks.
- MovieHub-owned writable data: host path `MOVIEHUB_DATA_PATH` mounted at `/data`.
- Dedicated backup destination: host path `MOVIEHUB_BACKUP_PATH` mounted at `/backups`.
  - SQLite database: `/data/db/movies.db`.
  - Poster cache: `/data/posters/`.
- Scout import source: `MOVIEHUB_IMPORT_PATH` mounted at `/imports:ro`.
- Nginx Proxy Manager: the service joins the existing external Docker network `chatgpt-browser_default`; configure its upstream as `moviehub:8000`.

The source mount is read-only at the container boundary. Keep the MovieHub database and Scout source in separate host directories. Never point `MOVIEHUB_DATA_PATH` at the Scout database directory.

## Prepare on the NAS

1. Copy `deploy/.env.example` to the project root as `.env`.
2. Set `MOVIEHUB_IMPORT_PATH` to the host directory containing the Scout SQLite source. Do not point it at the MovieHub data directory.
3. Generate a unique long `MOVIEHUB_API_KEY`.
4. Confirm the external Docker network `chatgpt-browser_default` exists. It is the shared network currently used by NPM in this NAS setup.
5. Create the data and backup directories and grant the configured container UID/GID write access. Defaults are UID/GID 10001:
   ```sh
   mkdir -p /volume1/docker/moviehub/data
   mkdir -p /volume1/backup/moviehub
   chown -R 10001:10001 /volume1/docker/moviehub/data /volume1/backup/moviehub
   ```
6. Ensure the import directory and Scout database are readable by UID/GID 10001. Do not change Scout ownership or permissions broadly just for MovieHub; use a dedicated read-only export/copy directory if required.

## Build and initialize

Run from the repository root:

```sh
docker compose build
docker compose run --rm --no-deps moviehub python -m scripts.init_db
docker compose up -d
```

The initializer creates a new independent MovieHub database at `/data/db/movies.db`. It refuses to initialize over a non-empty database. It does not modify Scout. Initialization is an explicit operator action and is not part of container startup.

Do not run the initializer against any existing Scout database or an existing production MovieHub database.

## NPM reverse proxy

Create a Proxy Host with:

- Forward hostname: `moviehub`
- Forward port: `8000`
- Scheme: `http`
- Websockets: off unless a future feature requires them

The Compose service is not published to the NAS host or LAN; it is reachable through the shared NPM Docker network. Keep API access behind NPM authentication/access controls as appropriate. Do not expose the import API publicly without an additional access-control decision.

Uvicorn trusts forwarded client headers only from `FORWARDED_ALLOW_IPS`. The Compose default trusts loopback only, so rate limiting may see the proxy address until you set `MOVIEHUB_TRUSTED_PROXY_IPS` to the exact NPM container IP or its dedicated Docker subnet. Inspect the actual network first; do not set this to `*`, which would let any reachable container spoof client IP headers.

## Health and readiness

- `GET /api/health`: process liveness.
- `GET /api/ready`: database readiness. The container health check uses this endpoint, so the container remains unhealthy until the explicit database initialization has succeeded.
- Database backup and restore commands are documented in [BACKUP-RESTORE.md](BACKUP-RESTORE.md); backups are stored on the dedicated `/backups` mount.
- Logs are written to stdout/stderr for Docker log collection.

The container runs as a non-root UID, drops Linux capabilities, uses a read-only root filesystem, and has CPU, memory and PID limits. The database and poster cache are writable only through the dedicated `/data` mount.

## Operational boundaries

- This package is an initial backend runtime baseline, not a production rollout approval.
- No production database, Scout import, NPM proxy host, firewall rule, or NAS service is changed by preparing these files.
- Before deployment, verify host directory permissions, Docker network name, backup/restore procedure, and API access policy.
- Frontend hosting, public routing, TLS, and any automated Scout import schedule remain separate future decisions.
