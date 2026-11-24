# Frontend and backend container deployment

Compose now defines two application containers: a static React frontend and the FastAPI backend. Both are internal-only and have no published NAS/LAN host ports. This is a packaging baseline, not approval to deploy. It does not initialize a database, import Scout data, or change NPM.

## Runtime layout

- API container: `moviehub-backend`, port 8000 on its Docker networks.
- Frontend container: `moviehub-web`, port 8080 on the NPM Docker network; serves the React/Vite build and client-side routes.
- Frontend runtime config: `MOVIEHUB_FRONTEND_CONFIG_PATH` mounted as `/usr/share/nginx/html/config.json`; set `xiaoyaSearchBaseUrl` there. Keep it a public URL only, never a secret.
- MovieHub-owned writable data: host path `MOVIEHUB_DATA_PATH` mounted at `/data`.
- Dedicated backup destination: host path `MOVIEHUB_BACKUP_PATH` mounted at `/backups`.
  - SQLite database: `/data/db/movies.db`.
  - Poster cache: `/data/posters/`.
- Optional Scout import source: when `MOVIEHUB_IMPORT_PATH` is set, that host directory is mounted at `/imports:ro`; when omitted, Compose mounts the tracked empty directory `./deploy/empty-imports`. MovieHub's own database initialization and normal runtime do not require Scout.
- Nginx Proxy Manager: the frontend and backend join the existing external Docker network `chatgpt-browser_default`; configure the default upstream as `moviehub-web:8080` and API custom locations as `moviehub:8000`.

The source mount is read-only at the container boundary. Keep the MovieHub database and Scout source in separate host directories. Never point `MOVIEHUB_DATA_PATH` at the Scout database directory.

## Prepare on the NAS

1. Copy `deploy/.env.example` to the project root as `.env`.
2. Scout is optional. If you need to import from Scout, set `MOVIEHUB_IMPORT_PATH` to a dedicated host directory containing a readable Scout SQLite source/export. If not using Scout, leave it unset; Compose uses an empty read-only mount. Never point it at the MovieHub data directory.
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

The frontend image is built separately from `frontend/` and served by an unprivileged Nginx process on port 8080. It uses a read-only root filesystem, a small `/tmp` tmpfs and a 128 MiB memory limit. The frontend config is a bind-mounted JSON file so the Xiaoya address can be changed without embedding the NAS hostname in source code.

The initializer creates a new independent MovieHub database at `/data/db/movies.db`. It refuses to initialize over a non-empty database. It does not modify Scout. Initialization is an explicit operator action and is not part of container startup.

Do not run the initializer against any existing Scout database or an existing production MovieHub database.

## NPM reverse proxy

Use one same-origin MovieHub host:

1. Proxy Host default upstream:
   - Forward hostname: `moviehub-web`
   - Forward port: `8080`
   - Scheme: `http`
2. Add a custom location `/api/` forwarding to `moviehub:8000`. Preserve the original URI so `/api/...` reaches FastAPI unchanged.
3. Add a more specific custom location `/api/favorites` forwarding to `moviehub:8000`, with an upstream-only header:
   ```nginx
   proxy_set_header X-API-Key "<MOVIEHUB_API_KEY>";
   ```
   Replace the placeholder with the private server-side key. Do not put the key in React/Vite environment variables, HTML, JavaScript or browser storage. This location is needed because favorites endpoints are protected but the browser must not know the secret.
4. Do not inject the key on the whole `/api/` location. The backend independently requires the key on both import endpoints, but browser-facing NPM routing should also deny them so they are not exposed as public operator functions. In the Proxy Host's server-level Advanced Nginx configuration, add:
   ```nginx
   location ^~ /api/import {
       return 404;
   }

   location ^~ /api/charts/import {
       return 404;
   }
   ```
   These longer `^~` prefixes take precedence over the general `/api/` proxy location and also cover `/api/import/status`. Validate the NPM configuration before applying it. Run operator imports through the CLI instead.
5. Keep NPM access controls and TLS enabled as appropriate for the host.

The frontend and backend are on the existing external Docker network `chatgpt-browser_default`; neither publishes a host port. Same-origin routing means no broad CORS allowlist is required.

Uvicorn trusts forwarded client headers only from `FORWARDED_ALLOW_IPS`. The Compose default trusts loopback only, so rate limiting may see the proxy address until you set `MOVIEHUB_TRUSTED_PROXY_IPS` to the exact NPM container IP or its dedicated Docker subnet. Inspect the actual network first; do not set this to `*` or a default route (`0.0.0.0/0`, `::/0`), which would let any reachable container spoof client IP headers.

## Health and readiness

- `GET /api/health`: process liveness.
- `GET /api/ready`: database readiness. The container health check uses this endpoint, so the container remains unhealthy until the explicit database initialization has succeeded.
- Database backup and restore commands are documented in [BACKUP-RESTORE.md](BACKUP-RESTORE.md); backups are stored on the dedicated `/backups` mount.
- Logs are written to stdout/stderr for Docker log collection.

The container runs as a non-root UID, drops Linux capabilities, uses a read-only root filesystem, and has CPU, memory and PID limits. The database and poster cache are writable only through the dedicated `/data` mount.

## Operational boundaries

- This package is an initial dual-container runtime baseline, not a production rollout approval.
- No production database, Scout import, NPM proxy host, firewall rule, or NAS service is changed by preparing these files.
- Before deployment, verify host directory permissions, Docker network name, backup/restore procedure, and API access policy.
- The frontend container and same-origin routing are packaged but not deployed. Actual NPM locations, TLS, access controls, and API-key injection remain operator configuration steps.
- Automated Douban chart acquisition and any Scout import schedule remain separate future work.


## Read-only preflight

Before building or starting either container on the NAS, run the repository's read-only host preflight from the project root:

```sh
python3 deploy/preflight.py
```

It checks the Compose v2 command/configuration, the private API-key placeholder, frontend runtime JSON, expected data/backup directories (including directory write and search mode bits), the external NPM Docker network, likely NPM network members, fixed MovieHub container-name conflicts, and the forwarded-header trust list. The trust list must be explicit IP/CIDR entries; wildcard `*` and default routes (`0.0.0.0/0`, `::/0`) are rejected. It never creates directories, changes ownership, initializes SQLite, starts/stops containers, changes Docker networks, or edits NPM.

Treat mode-bit results as advisory on DSM because ACLs may grant or deny access independently. Confirm actual write access as UID/GID 10001 before deployment. The script cannot verify NPM's saved proxy-host configuration, TLS, access lists, or whether import endpoints are denied; those remain a separate manual review gate. A successful preflight is not deployment authorization.
