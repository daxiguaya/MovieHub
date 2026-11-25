# Frontend and backend container deployment

Compose now defines two application containers: a static React frontend and the FastAPI backend. Both are internal-only and have no published NAS/LAN host ports. This guide includes the original bootstrap procedure and the current runtime layout. For an existing production NAS instance, do not rerun the initial database initializer; use the reviewed rollout/import scripts and their preflight/backup safeguards. This document does not authorize NPM changes or service restarts.

## Runtime layout

- API container: `moviehub-backend`, port 8000 on its Docker networks.
- Frontend container: `moviehub-web`, port 8080 on the NPM Docker network; serves the React/Vite build and client-side routes.
- Frontend runtime config: `MOVIEHUB_FRONTEND_CONFIG_PATH` mounted as `/usr/share/nginx/html/config.json`; the `.env` variable `MOVIEHUB_XIAOYA_SEARCH_URL_TEMPLATE` (with `{query}` placeholder). The backend exposes it through `/api/config` as `xiaoyaSearchUrlTemplate`; it is public navigation configuration, never a secret.
- MovieHub-owned writable data: host path `MOVIEHUB_DATA_PATH` mounted at `/data`.
- Dedicated backup destination: host path `MOVIEHUB_BACKUP_PATH` mounted at `/backups`.
  - SQLite database: `/data/db/movies.db`.
  - Poster cache: `/data/posters/`.
- Optional Scout import source: when `MOVIEHUB_IMPORT_PATH` is set, that host directory is mounted at `/imports:ro`; when omitted, Compose mounts the tracked empty directory `./deploy/empty-imports`. MovieHub's own database initialization and normal runtime do not require Scout.
- Nginx Proxy Manager: the frontend and backend join the existing external Docker network `nginx-proxy-manager_default`; configure the default upstream as `moviehub-web:8080` and API custom locations as `moviehub:8000`.

The source mount is read-only at the container boundary. Keep the MovieHub database and Scout source in separate host directories. Never point `MOVIEHUB_DATA_PATH` at the Scout database directory.

## Prepare on the NAS

1. Copy `deploy/.env.example` to the project root as `.env`.
2. Scout is optional. If you need to import from Scout, set `MOVIEHUB_IMPORT_PATH` to a dedicated host directory containing a readable Scout SQLite source/export. If not using Scout, leave it unset; Compose uses an empty read-only mount. Never point it at the MovieHub data directory.
3. Generate a unique long `MOVIEHUB_API_KEY`.
4. Confirm the external Docker network `nginx-proxy-manager_default` exists. It is the shared network currently used by NPM in this NAS setup.
5. Create the data and backup directories and grant the configured container UID/GID write access. Defaults are UID/GID 10001:
   ```sh
   mkdir -p /volume1/docker/moviehub/data
   mkdir -p /volume1/docker/moviehub/backup
   chown -R 10001:10001 /volume1/docker/moviehub/data /volume1/docker/moviehub/backup
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

## NPM reverse proxy under an existing site's path

The frontend image is built with `MOVIEHUB_BASE_PATH=/moviehub/` by default. It supports both this path deployment and a root deployment (build with `MOVIEHUB_BASE_PATH=/`). React Router, static assets, runtime config, poster URLs, and API requests all use the configured base path.

For an existing NPM Proxy Host that already serves DSM at the root of `zwnas.notedream.com:18443`, add only path-specific locations. Do not change the existing default upstream, TLS certificate, access list, or other site's configuration.

1. Add a custom location `/moviehub/`:
   - Scheme: `http`
   - Forward hostname: `moviehub-web`
   - Forward port: `8080`
   - Preserve the incoming URI. Do not append or strip `/moviehub/`.
2. Add a more-specific custom location `/moviehub/api/favorites` with the same frontend upstream (`moviehub-web:8080`). In that location's Advanced configuration, inject the secret only on the upstream request:
   ```nginx
   proxy_set_header X-API-Key "<MOVIEHUB_API_KEY>";
   ```
   Replace the placeholder locally with the private key. Never put it in React/Vite variables, HTML, JavaScript, browser storage, or this repository. The frontend Nginx forwards this header to FastAPI. Do not inject it on the entire `/moviehub/` location.
3. In the Proxy Host's server-level Advanced Nginx configuration, deny both import route families:
   ```nginx
   location ^~ /moviehub/api/import {
       return 404;
   }

   location ^~ /moviehub/api/charts/import {
       return 404;
   }
   ```
   These prefixes also cover their status endpoints. Keep these deny locations more specific than the general `/moviehub/` custom location. Run operator imports through the CLI, not through the public browser route.
4. The frontend Nginx internally proxies `/moviehub/api/...` to `moviehub:8000/api/...`. Do not create a separate NPM API location to the backend; the backend remains reachable only through the Docker network.
5. Validate the NPM configuration before applying it. Keep the existing TLS and access controls enabled.

The frontend container and backend both join `nginx-proxy-manager_default`. NPM forwards to the frontend only; the frontend proxies API requests to the backend. No host ports are published. Same-origin routing means no broad CORS allowlist is required.

Because the frontend Nginx is now the immediate proxy seen by FastAPI, set `MOVIEHUB_TRUSTED_PROXY_IPS` to the frontend container's exact IP on `nginx-proxy-manager_default` (inspect it after the frontend container is recreated). Do not leave it set to the NPM container IP, and never use `*` or a default route (`0.0.0.0/0`, `::/0`). The frontend forwards the original client address chain to FastAPI.

## Health and readiness

- `GET /api/health`: process liveness.
- `GET /api/ready`: database readiness. The container health check uses this endpoint, so the container remains unhealthy until the explicit database initialization has succeeded.
- Database backup and restore commands are documented in [BACKUP-RESTORE.md](BACKUP-RESTORE.md); backups are stored on the dedicated `/backups` mount.
- Logs are written to stdout/stderr for Docker log collection.

The container runs as a non-root UID, drops Linux capabilities, uses a read-only root filesystem, and has memory and PID limits. CPU quota is omitted because some DSM kernels do not support Docker's CFS/NanoCPU controls. The database and poster cache are writable only through the dedicated `/data` mount.

## Operational boundaries

- This package is an initial dual-container runtime baseline, not a production rollout approval.
- No production database, Scout import, NPM proxy host, firewall rule, or NAS service is changed by preparing these files.
- Before deployment, verify host directory permissions, Docker network name, backup/restore procedure, and API access policy.
- The frontend container and same-origin routing are packaged and can be deployed under `/moviehub/`. Actual NPM locations, TLS, access controls, and API-key injection remain operator configuration steps.
- Automated Douban chart acquisition and any Scout import schedule remain separate future work.


## Read-only preflight

Before building or starting either container on the NAS, run the repository's read-only host preflight from the project root:

```sh
python3 deploy/preflight.py
```

It checks the Compose v2 command/configuration, the private API-key placeholder, frontend runtime JSON, expected data/backup directories (including directory write and search mode bits), the external NPM Docker network, likely NPM network members, fixed MovieHub container-name conflicts, and the forwarded-header trust list. The trust list must be explicit IP/CIDR entries; wildcard `*` and default routes (`0.0.0.0/0`, `::/0`) are rejected. It never creates directories, changes ownership, initializes SQLite, starts/stops containers, changes Docker networks, or edits NPM.

Treat mode-bit results as advisory on DSM because ACLs may grant or deny access independently. Confirm actual write access as UID/GID 10001 before deployment. The script cannot verify NPM's saved proxy-host configuration, TLS, access lists, or whether import endpoints are denied; those remain a separate manual review gate. A successful preflight is not deployment authorization.
