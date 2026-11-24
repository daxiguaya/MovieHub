# MovieHub database backup and restore

The backup utility operates only on the MovieHub-owned database. It never opens or modifies the Douban Scout source database.

## Backup contents and guarantees

- Uses SQLite's online backup API, so a consistent database snapshot can be created while the API is running.
- Verifies SQLite integrity, foreign-key consistency and the expected MovieHub schema version before and after copying.
- Writes a SHA-256 checksum and metadata manifest beside each backup.
- Keeps the newest seven backup directories by default.
- Does not back up the poster cache. Posters are cached assets and can be fetched again; the SQLite database is the authoritative data.
- Never removes or overwrites the live database during backup.

The backup directory is mounted at `/backups`, separately from MovieHub's writable data directory at `/data`.

## Prepare the backup destination

Set `MOVIEHUB_BACKUP_PATH` in the project `.env` file. The Compose default is `/volume1/backup/moviehub`.

Create it and grant the container UID/GID write access (defaults to 10001:10001):

```sh
mkdir -p /volume1/backup/moviehub
chown -R 10001:10001 /volume1/backup/moviehub
```

Prefer a different physical volume or a separate/off-site destination for disaster recovery. A backup on the same disk does not protect against disk failure.

## Create a backup

With the API container running:

```sh
docker compose exec moviehub python -m scripts.db_backup backup
```

The command prints the created directory, for example `/backups/moviehub-20261123T070000000000Z`. Each directory contains:

- `movies.db`: consistent SQLite backup.
- `manifest.json`: schema version, timestamp, size and SHA-256 checksum.

To retain a different number of backup generations:

```sh
docker compose exec moviehub python -m scripts.db_backup backup --keep-last 14
```

Do not manually edit the backup database or manifest. Protect the backup directory as sensitive application data.

## Restore a backup

Restore is intentionally a separate, destructive operation. First select and verify the backup directory. Then stop the API container so no process can write to the live database:

```sh
docker compose stop moviehub
```

Run the restore as a one-shot container. Replace the example directory with the exact existing backup directory:

```sh
docker compose run --rm --no-deps moviehub \
  python -m scripts.db_backup restore \
  --backup-dir /backups/moviehub-YYYYMMDDTHHMMSSffffffZ \
  --confirm --service-stopped
```

The restore utility:
1. Verifies the manifest checksum, schema version, SQLite integrity and foreign keys before touching the live database.
2. Creates a separate pre-restore rollback copy of the current MovieHub database when one exists.
3. Replaces the database atomically and validates the restored file.
4. Restores the pre-restore copy if post-replacement validation fails.

After a successful restore:

```sh
docker compose up -d
docker compose logs --tail=100 moviehub
```

Check `/api/ready` and verify the expected chart/movie data before considering the restore complete. Keep the pre-restore rollback copy until the restored service has been checked.

The restore command requires both `--confirm` and `--service-stopped`. These flags are an explicit operator acknowledgement; they do not themselves stop or inspect the API container.

## Safety boundaries

- Never use a Scout database path as the restore destination.
- Never run restore while the MovieHub API is running.
- Do not delete the pre-restore rollback copy until recovery has been verified.
- Keep backups outside Git and outside the application source tree.
- This runbook does not authorize production initialization, Scout import, or deployment.


## Isolated lifecycle rehearsal (CI)

The backend test suite includes a single end-to-end filesystem-isolated lifecycle check:

1. Confirm readiness is false before initialization.
2. Initialize a brand-new MovieHub database in a temporary directory and confirm readiness becomes true.
3. Insert a known record and create a verified backup.
4. Insert a post-backup change to simulate later writes.
5. Restore the selected backup with the explicit confirmation flags.
6. Confirm the original data is restored, the pre-restore rollback copy contains the later change, readiness is true, schema version is current, and SQLite integrity/foreign-key checks are clean.
7. Separately verify that initialization refuses an existing external database and leaves its source table and records unchanged.

This is an automated rehearsal of the database lifecycle, not a live Docker/NPM/NAS deployment. Compose configuration validation and container builds are separate CI checks. No production database is initialized or modified by these tests.
