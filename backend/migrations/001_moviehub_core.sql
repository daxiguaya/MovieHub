
-- MovieHub migration 001
-- Target: existing douban-scout database
-- Run once against a staging copy before production.
--
-- IMPORTANT:
-- This migration assumes the original Scout schema and must be executed
-- through the migration runner, not pasted into an arbitrary SQLite session.

PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- -------------------------------------------------------------------------
-- 1. Migration tracking
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- -------------------------------------------------------------------------
-- 2. Extend the existing Scout movies table
-- -------------------------------------------------------------------------

ALTER TABLE movies ADD COLUMN douban_id TEXT;
ALTER TABLE movies ADD COLUMN imdb_id TEXT;
ALTER TABLE movies ADD COLUMN tmdb_id TEXT;
ALTER TABLE movies ADD COLUMN original_title TEXT;
ALTER TABLE movies ADD COLUMN directors TEXT NOT NULL DEFAULT '[]';
ALTER TABLE movies ADD COLUMN actors TEXT NOT NULL DEFAULT '[]';
ALTER TABLE movies ADD COLUMN overview TEXT;
ALTER TABLE movies ADD COLUMN douban_url TEXT;

-- Existing Scout imports used the Douban ID as movies.id.
-- Preserve that identity when upgrading an existing database.
UPDATE movies
SET douban_id = CAST(id AS TEXT)
WHERE douban_id IS NULL OR douban_id = '';

-- The external identifier is unique but is not the internal primary key.
CREATE UNIQUE INDEX IF NOT EXISTS ux_movies_douban_id
ON movies(douban_id);

CREATE INDEX IF NOT EXISTS ix_movies_imdb_id
ON movies(imdb_id);

CREATE INDEX IF NOT EXISTS ix_movies_tmdb_id
ON movies(tmdb_id);

-- -------------------------------------------------------------------------
-- 2.5 Normalized movie metadata tables used by the ORM
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_genres_name ON genres(name);

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id INTEGER NOT NULL,
    genre_id INTEGER NOT NULL,
    PRIMARY KEY (movie_id, genre_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_regions_name ON regions(name);

CREATE TABLE IF NOT EXISTS movie_regions (
    movie_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    PRIMARY KEY (movie_id, region_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES regions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movie_posters (
    movie_id INTEGER NOT NULL,
    url VARCHAR(512) NOT NULL,
    PRIMARY KEY (movie_id, url),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

-- -------------------------------------------------------------------------
-- 3. Chart definitions
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS lists (
    list_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    period TEXT,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_lists_slug
ON lists(slug);

-- -------------------------------------------------------------------------
-- 4. Dated chart snapshots
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS list_items (
    list_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    douban_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    source_rating REAL,

    PRIMARY KEY (
        list_id,
        snapshot_date,
        douban_id
    ),

    CONSTRAINT fk_list_items_list
        FOREIGN KEY (list_id)
        REFERENCES lists(list_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_list_items_movie
        FOREIGN KEY (douban_id)
        REFERENCES movies(douban_id)
        ON DELETE RESTRICT,

    CONSTRAINT uq_list_items_snapshot_rank
        UNIQUE (list_id, snapshot_date, rank)
);

CREATE INDEX IF NOT EXISTS ix_list_items_douban_id
ON list_items(douban_id);

CREATE INDEX IF NOT EXISTS ix_list_items_snapshot_rank
ON list_items(list_id, snapshot_date, rank);

-- -------------------------------------------------------------------------
-- 5. Favorites table (feature reserved for a later phase)
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS favorites (
    douban_id TEXT PRIMARY KEY,
    created_at TEXT,
    note TEXT NOT NULL DEFAULT '',

    CONSTRAINT fk_favorites_movie
        FOREIGN KEY (douban_id)
        REFERENCES movies(douban_id)
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------------
-- 7. Record migration
-- -------------------------------------------------------------------------

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (
    1,
    'moviehub_core',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);

COMMIT;

