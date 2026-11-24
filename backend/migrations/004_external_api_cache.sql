-- MovieHub migration 004: bounded persistent cache for external API responses.
-- Cache rows are disposable; favorites and chart snapshots are stored elsewhere.

BEGIN IMMEDIATE;

CREATE TABLE external_api_cache (
    cache_key VARCHAR(64) PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    endpoint VARCHAR(128) NOT NULL,
    params_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_accessed_at INTEGER NOT NULL,
    payload_bytes INTEGER NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_external_api_cache_payload_bytes CHECK (payload_bytes >= 0),
    CONSTRAINT ck_external_api_cache_hit_count CHECK (hit_count >= 0)
);
CREATE INDEX ix_external_api_cache_expires_at
    ON external_api_cache(expires_at);
CREATE INDEX ix_external_api_cache_last_accessed_at
    ON external_api_cache(last_accessed_at);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (4, 'bounded_external_api_cache', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;