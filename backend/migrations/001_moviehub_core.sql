-- MovieHub migration 001: initialize an independent MovieHub database.
-- This script is only for a new, empty SQLite database.
-- Douban Scout is an external read-only source and is never altered here.

PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    douban_id VARCHAR(32),
    imdb_id VARCHAR(32),
    tmdb_id VARCHAR(32),
    title VARCHAR(256) NOT NULL,
    original_title VARCHAR(256),
    year INTEGER,
    rating FLOAT,
    rating_count INTEGER NOT NULL DEFAULT 0 CHECK (rating_count >= 0),
    type VARCHAR(16) NOT NULL DEFAULT 'movie' CHECK (type IN ('movie', 'tv')),
    directors TEXT NOT NULL DEFAULT '[]',
    actors TEXT NOT NULL DEFAULT '[]',
    overview TEXT,
    douban_url VARCHAR(512),
    updated_at INTEGER,
    CONSTRAINT uq_movies_douban_id UNIQUE (douban_id),
    CONSTRAINT uq_movies_imdb_id UNIQUE (imdb_id),
    CONSTRAINT uq_movies_tmdb_id UNIQUE (tmdb_id),
    CONSTRAINT ck_movies_rating CHECK (rating IS NULL OR (rating >= 0 AND rating <= 10))
);

CREATE INDEX ix_movies_douban_id ON movies(douban_id);
CREATE INDEX ix_movies_imdb_id ON movies(imdb_id);
CREATE INDEX ix_movies_tmdb_id ON movies(tmdb_id);
CREATE INDEX ix_movies_title ON movies(title);
CREATE INDEX ix_movies_original_title ON movies(original_title);
CREATE INDEX ix_movies_year ON movies(year);
CREATE INDEX ix_movies_rating ON movies(rating);
CREATE INDEX ix_movies_rating_count ON movies(rating_count);
CREATE INDEX ix_movies_type ON movies(type);
CREATE INDEX ix_movies_rating_id ON movies(rating, id);
CREATE INDEX ix_movies_year_id ON movies(year, id);
CREATE INDEX ix_movies_rating_count_id ON movies(rating_count, id);

CREATE TABLE genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE
);
CREATE INDEX ix_genres_name ON genres(name);

CREATE TABLE regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE
);
CREATE INDEX ix_regions_name ON regions(name);

CREATE TABLE movie_genres (
    movie_id INTEGER NOT NULL,
    genre_id INTEGER NOT NULL,
    PRIMARY KEY (movie_id, genre_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
);

CREATE TABLE movie_regions (
    movie_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    PRIMARY KEY (movie_id, region_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES regions(id) ON DELETE CASCADE
);

CREATE TABLE movie_posters (
    movie_id INTEGER NOT NULL,
    url VARCHAR(512) NOT NULL,
    PRIMARY KEY (movie_id, url),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

CREATE TABLE lists (
    list_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug VARCHAR(96) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    source VARCHAR(32) NOT NULL,
    category VARCHAR(32) NOT NULL,
    period VARCHAR(32),
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0,
    last_updated DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE INDEX ix_lists_slug ON lists(slug);
CREATE INDEX ix_lists_source ON lists(source);
CREATE INDEX ix_lists_category ON lists(category);

CREATE TABLE chart_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL,
    snapshot_date VARCHAR(10) NOT NULL,
    imported_at DATETIME NOT NULL,
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    CONSTRAINT uq_chart_snapshots_list_date UNIQUE (list_id, snapshot_date),
    FOREIGN KEY (list_id) REFERENCES lists(list_id) ON DELETE CASCADE
);
CREATE INDEX ix_chart_snapshots_list_id ON chart_snapshots(list_id);
CREATE INDEX ix_chart_snapshots_snapshot_date ON chart_snapshots(snapshot_date);

CREATE TABLE list_items (
    snapshot_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    source_rating FLOAT,
    PRIMARY KEY (snapshot_id, movie_id),
    CONSTRAINT uq_list_items_snapshot_rank UNIQUE (snapshot_id, rank),
    CONSTRAINT ck_list_items_source_rating CHECK (
        source_rating IS NULL OR (source_rating >= 0 AND source_rating <= 10)
    ),
    FOREIGN KEY (snapshot_id) REFERENCES chart_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE RESTRICT
);
CREATE INDEX ix_list_items_snapshot_rank ON list_items(snapshot_id, rank);
CREATE INDEX ix_list_items_movie_id ON list_items(movie_id);

CREATE TABLE favorites (
    movie_id INTEGER PRIMARY KEY,
    created_at DATETIME NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE RESTRICT
);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (1, 'moviehub_core', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
