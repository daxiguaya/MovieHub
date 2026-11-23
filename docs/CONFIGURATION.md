# Configuration

MovieHub reads configuration from environment variables with the `MOVIEHUB_` prefix.

| Variable | Default | Purpose |
|---|---|---|
| `MOVIEHUB_DATA_DIR` | `/data` | MovieHub-owned database and poster-cache root |
| `MOVIEHUB_BACKUP_DIR` | `/backups` | Dedicated backup destination inside the container |
| `MOVIEHUB_IMPORT_DIR` | `/imports` | Directory from which Scout source databases may be imported |
| `MOVIEHUB_API_KEY` | empty | Required to enable protected import APIs |
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

## Protected import API

Set a strong, private `MOVIEHUB_API_KEY`. Requests to protected import endpoints must send it in the `X-API-Key` header. When no key is configured, protected import APIs return HTTP 503 and remain disabled.

The Scout source database must be located under `MOVIEHUB_IMPORT_DIR`. The API resolves the requested path and rejects paths or symlinks that escape that directory. MovieHub opens Scout SQLite files in read-only mode; mount the source directory read-only as an additional filesystem boundary.

## Database lifecycle

MovieHub does not create or migrate a database during module import or application startup. Initialize a new, independent MovieHub database explicitly from the backend directory:

```bash
python -m scripts.init_db
```

The initializer creates and validates a temporary database before atomically publishing it. It refuses to convert or overwrite an existing non-empty unrecognized database. Douban Scout is not the MovieHub database and must never be passed to this initializer or migration runner.

- `GET /api/health` is a process liveness check.
- `GET /api/ready` checks that the MovieHub schema is present and at the supported schema version.
- Data APIs return HTTP 503 until the MovieHub database has been initialized.

Do not run initialization or migrations against production data until a separate deployment and backup procedure has been reviewed.
