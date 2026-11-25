-- MovieHub migration 004: represent unknown Douban vote counts as NULL.
-- Existing zero values came from adapters that had no vote-count field.
-- Preserve every movie identity and relationship while rebuilding only movies.

PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE movies_new (
    id INTEGER PRIMARY KEY,
    douban_id VARCHAR(32),
    imdb_id VARCHAR(32),
    tmdb_id VARCHAR(32),
    title VARCHAR(256) NOT NULL,
    original_title VARCHAR(256),
    year INTEGER,
    rating FLOAT,
    rating_count INTEGER DEFAULT NULL,
    type VARCHAR(16) NOT NULL DEFAULT 'movie',
    directors TEXT NOT NULL DEFAULT '[]',
    actors TEXT NOT NULL DEFAULT '[]',
    overview TEXT,
    douban_url VARCHAR(512),
    updated_at INTEGER,
    CONSTRAINT ck_movies_rating CHECK (rating IS NULL OR (rating >= 0 AND rating <= 10)),
    CONSTRAINT ck_movies_rating_count CHECK (rating_count IS NULL OR rating_count >= 0),
    CONSTRAINT ck_movies_type CHECK (type IN ('movie', 'tv'))
);

INSERT INTO movies_new (
    id, douban_id, imdb_id, tmdb_id, title, original_title, year, rating,
    rating_count, type, directors, actors, overview, douban_url, updated_at
)
SELECT
    id, douban_id, imdb_id, tmdb_id, title, original_title, year, rating,
    NULLIF(rating_count, 0), type, directors, actors, overview, douban_url, updated_at
FROM movies;

DROP TABLE movies;
ALTER TABLE movies_new RENAME TO movies;

CREATE UNIQUE INDEX ix_movies_douban_id ON movies(douban_id);
CREATE UNIQUE INDEX ix_movies_imdb_id ON movies(imdb_id);
CREATE UNIQUE INDEX ix_movies_tmdb_id ON movies(tmdb_id);
CREATE INDEX ix_movies_title ON movies(title);
CREATE INDEX ix_movies_original_title ON movies(original_title);
CREATE INDEX ix_movies_year ON movies(year);
CREATE INDEX ix_movies_rating ON movies(rating);
CREATE INDEX ix_movies_rating_count ON movies(rating_count);
CREATE INDEX ix_movies_type ON movies(type);
CREATE INDEX ix_movies_rating_id ON movies(rating, id);
CREATE INDEX ix_movies_year_id ON movies(year, id);
CREATE INDEX ix_movies_rating_count_id ON movies(rating_count, id);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (4, 'nullable_douban_vote_count', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
PRAGMA foreign_keys = ON;
