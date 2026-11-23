# Douban Scout import runbook

MovieHub imports Scout data into its own database. The source is opened read-only and must be inside the configured `MOVIEHUB_IMPORT_PATH` host directory, mounted as `/imports:ro`.

## Before importing

1. Initialize the independent MovieHub database explicitly and confirm `GET /api/ready` returns success.
2. Set `MOVIEHUB_IMPORT_PATH` to a dedicated directory containing the Scout database or a consistent read-only copy.
3. Do not point `MOVIEHUB_DATA_PATH` at Scout. Do not run MovieHub migrations or initialization against Scout.
4. Ensure any SQLite WAL sidecar files required for a consistent source read are present and readable in the mounted directory. Prefer a SQLite online-backup copy when staging a snapshot; do not copy only the main database file while Scout is actively writing in WAL mode.
5. Keep the API key private. The favorites-only NPM header injection described in [DEPLOYMENT.md](DEPLOYMENT.md) must not be applied to the entire `/api/` path.

## Start an incremental import

Send a protected request from an authorized operator workstation:

```sh
curl -X POST "https://<moviehub-host>/api/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <MOVIEHUB_API_KEY>" \
  -d '{"source_path":"scout.sqlite","force_full":false}'
```

The `source_path` is relative to `/imports` in this example. The endpoint rejects paths that resolve outside the configured import directory.

Check progress:

```sh
curl "https://<moviehub-host>/api/import/status" \
  -H "X-API-Key: <MOVIEHUB_API_KEY>"
```

Only one import can run at a time. The service processes 500 records per transaction and isolates individual bad records with SAVEPOINTs.

## Incremental vs. forced full

- `force_full: false`: for an existing MovieHub movie, skip the source row when Scout `update_time` is not newer than MovieHub's last imported source timestamp. New rows are imported normally.
- `force_full: true`: reprocess all valid source rows even when timestamps are unchanged. Use this after changing field-mapping or merge logic.
- A non-empty Scout field can refresh its corresponding MovieHub field. Missing/empty source fields do not erase populated MovieHub metadata.
- Scout rows that disappear are not deletion instructions. MovieHub retains previously imported movies.
- If a later batch fails, earlier committed batches remain. Fix the cause and retry; the import is designed to be idempotent.

## After importing

- Confirm status is `completed` and inspect backend logs for skipped/error records.
- Check MovieHub movie counts and a few known records using the read APIs.
- Do not edit the Scout database or remove source rows to make MovieHub match a desired catalogue.
- Do not treat a successful metadata import as chart acquisition. Chart snapshots use the separate normalized JSON workflow in [CHART-IMPORT.md](CHART-IMPORT.md).

## Production boundary

This runbook documents the operator procedure only. It does not authorize importing the user's live Scout database, creating a production MovieHub database, changing NPM, or restarting any NAS service. Perform those actions only after a separate review and explicit approval.


## Optional synthetic import benchmark

The repository includes opt-in 10,000-row and 100,000-row synthetic import benchmarks. They generate temporary Scout-shaped SQLite source files and import into temporary MovieHub SQLite databases through the production `ImportService`; no real Scout or MovieHub database is opened.

Run from the `backend/` directory:

```sh
MOVIEHUB_RUN_IMPORT_BENCHMARKS=1 pytest -q -s tests/test_import_performance.py
```

The output reports elapsed time, rows per second and the configured transaction batch size. These cases are skipped by default in CI because throughput and memory behavior depend on the runner and storage hardware. Run them first on a controlled test machine; repeat on the NAS only as part of a separately authorized pre-deployment test. The benchmark does not deploy the application or touch production data.
