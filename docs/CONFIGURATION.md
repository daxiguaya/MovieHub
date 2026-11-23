# Configuration

MovieHub reads configuration from environment variables with the `MOVIEHUB_` prefix.

| Variable | Default | Purpose |
|---|---|---|
| `MOVIEHUB_DATA_DIR` | `/data` | MovieHub-owned database and poster-cache root |
| `MOVIEHUB_BACKUP_DIR` | `/backups` | Dedicated backup destination inside the container |
| `MOVIEHUB_IMPORT_DIR` | `/imports` | Directory from which Scout source databases may be imported |
| `MOVIEHUB_API_KEY` | empty | Required for protected import, chart-import and favorites write/read APIs |
| `MOVIEHUB_CORS_ORIGINS` | `[]` | Explicit JSON array of allowed cross-origin frontend origins |
| `MOVIEHUB_LOG_LEVEL` | `INFO` | Console logging level |
| `MOVIEHUB_RATE_LIMIT_IMPORT` | `5/minute` | Rate limit for protected import APIs |

## CORS

Cross-origin access is disabled by default. Same-origin access through a single reverse-proxy host does not require CORS.

If a separate frontend origin is required, set an explicit JSON array, for example:

```dotenv
MOVIEHUB_CORS_ORIGINS=["https://moviehub.example.com"]
```

Do not use a wildcard origin. MovieHub does not enable credentialed CORS.

## Protected API access

Set a strong, private `MOVIEHUB_API_KEY`. Requests to protected import, chart-import and favorites endpoints must send it in the `X-API-Key` header. When no key is configured, protected endpoints return HTTP 503 and remain disabled.

The browser frontend must never embed this secret in JavaScript. For a same-origin Nginx Proxy Manager deployment, configure the `/api/favorites` location to inject the secret as an upstream `X-API-Key` header, or provide an equivalent server-side authenticated proxy. Keep the key only in private server-side configuration. Do not expose a client-side API-key value.

The Scout source database must be located under `MOVIEHUB_IMPORT_DIR`. The API resolves the requested path and rejects paths or symlinks that escape that directory. MovieHub opens Scout SQLite files in read-only mode; mount the source directory read-only as an additional filesystem boundary.

## Database lifecycle

MovieHub does not create or migrate a database during module import or application startup. Initialize a new, independent MovieHub database explicitly from the backend directory:

```bash
python -m scripts.init_db
```

The initializer applies the core schema and bundled follow-up migrations, validates a temporary schema-v2 database against the ORM contract, then atomically publishes it. It refuses to convert or overwrite an existing non-empty database. To upgrade an existing MovieHub schema-v1 database, stop the application and run `python -m scripts.migrate`; the runner creates and verifies a pre-migration backup and restores it if migration validation fails. Douban Scout is not the MovieHub database and must never be passed to this initializer or migration runner.

- `GET /api/health` is a process liveness check.
- `GET /api/ready` checks that the MovieHub schema is present and at the supported schema version.
- Data APIs return HTTP 503 until the MovieHub database has been initialized.

Do not run initialization or migrations against production data until a separate deployment and backup procedure has been reviewed.

## Frontend runtime configuration

The frontend reads the public Xiaoya search URL from `/config.json`. In Compose, `MOVIEHUB_FRONTEND_CONFIG_PATH` mounts the host JSON file at that path. The example file is `deploy/frontend-config.json`:

```json
{
  "xiaoyaSearchBaseUrl": "https://your-xiaoya-host.example/search"
}
```

The value is a public navigation URL, not a credential. MovieHub appends the selected movie title as the URL-encoded `box` query parameter. Keep the real NAS hostname in this runtime config rather than hardcoding it in the React source.

Never put `MOVIEHUB_API_KEY` or any other secret in this file. The frontend must not contain server credentials.
