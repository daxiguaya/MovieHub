-- MovieHub migration 003: field-level metadata provenance.
-- Records the source, observation time and value fingerprint for each accepted field.

BEGIN IMMEDIATE;

CREATE TABLE movie_metadata_provenance (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL,
    field_name VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    source_url VARCHAR(512) NOT NULL DEFAULT '',
    observed_at DATETIME NOT NULL,
    value_sha256 VARCHAR(64) NOT NULL,
    CONSTRAINT uq_movie_metadata_provenance_observation
        UNIQUE (movie_id, field_name, source, source_url, value_sha256),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
CREATE INDEX ix_movie_metadata_provenance_movie_field
    ON movie_metadata_provenance(movie_id, field_name);
CREATE INDEX ix_movie_metadata_provenance_observed_at
    ON movie_metadata_provenance(observed_at);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (3, 'movie_metadata_provenance', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
