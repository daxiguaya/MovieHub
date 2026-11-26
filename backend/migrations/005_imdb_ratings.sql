-- MovieHub migration 005: keep IMDb ratings separate from legacy Douban ratings.
-- Existing movies.rating/rating_count remain untouched for Douban chart history.

BEGIN IMMEDIATE;

ALTER TABLE movies
    ADD COLUMN imdb_rating FLOAT
    CONSTRAINT ck_movies_imdb_rating
    CHECK (imdb_rating IS NULL OR (imdb_rating >= 0 AND imdb_rating <= 10));

ALTER TABLE movies
    ADD COLUMN imdb_rating_count INTEGER
    CONSTRAINT ck_movies_imdb_rating_count
    CHECK (imdb_rating_count IS NULL OR imdb_rating_count >= 0);

CREATE INDEX ix_movies_imdb_rating ON movies(imdb_rating);
CREATE INDEX ix_movies_imdb_rating_count ON movies(imdb_rating_count);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (5, 'imdb_ratings', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
