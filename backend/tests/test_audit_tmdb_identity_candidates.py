import json
import sqlite3

from scripts.audit_tmdb_identity_candidates import audit_candidates


def make_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE movies (
            id INTEGER PRIMARY KEY, douban_id TEXT, imdb_id TEXT, tmdb_id TEXT,
            title TEXT NOT NULL, original_title TEXT, year INTEGER,
            type TEXT NOT NULL, directors TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO movies VALUES
            (1, 'db1', NULL, NULL, '肖申克的救赎', 'The Shawshank Redemption', 1994, 'movie', '["弗兰克·德拉邦特"]'),
            (2, 'db2', NULL, NULL, '未知电影', NULL, 2020, 'movie', '[]'),
            (3, 'db3', NULL, NULL, '没有结果', NULL, 2021, 'movie', '[]');
        """
    )
    connection.commit()
    connection.close()


class FakeLookup:
    def __init__(self, token):
        assert token == "not-a-real-token"
        self.calls = 0

    def get(self, endpoint, params=None):
        self.calls += 1
        if endpoint == "/search/movie":
            query = params["query"]
            if query in ("肖申克的救赎", "The Shawshank Redemption"):
                return {"results": [{
                    "id": 278, "title": "肖申克的救赎",
                    "original_title": "The Shawshank Redemption",
                    "release_date": "1994-09-23",
                }]}
            if query == "未知电影":
                return {"results": [{
                    "id": 999, "title": "未知电影",
                    "original_title": "Unknown Film", "release_date": "2020-01-01",
                }]}
            return {"results": []}
        if endpoint == "/movie/278":
            return {"credits": {"crew": [
                {"job": "Director", "name": "弗兰克·德拉邦特"}
            ]}}
        if endpoint == "/movie/999":
            return {"credits": {"crew": []}}
        raise AssertionError(endpoint)

    def close(self):
        pass


def test_candidate_audit_is_read_only_and_classifies_evidence(tmp_path):
    path = tmp_path / "movies.db"
    make_db(path)
    before = path.read_bytes()

    report = audit_candidates(path, "not-a-real-token", limit=0, lookup_factory=FakeLookup)

    assert report["read_only"] is True
    assert report["total_missing_tmdb_id"] == 3
    assert report["processed"] == 3
    assert report["counts"] == {
        "verified_candidate": 1, "needs_review": 1, "no_match": 1
    }
    assert report["results"][0]["verified_candidates"][0]["tmdb_id"] == 278
    assert "director_exact" in report["results"][0]["verified_candidates"][0]["evidence"]
    assert report["results"][1]["status"] == "needs_review"
    assert report["results"][2]["status"] == "no_match"
    assert path.read_bytes() == before


def test_candidate_audit_limit_does_not_claim_unprocessed_records(tmp_path):
    path = tmp_path / "movies.db"
    make_db(path)

    report = audit_candidates(path, "not-a-real-token", limit=1, lookup_factory=FakeLookup)

    assert report["processed"] == 1
    assert report["total_missing_tmdb_id"] == 3
    assert report["remaining_not_processed"] == 2


class FailingLookup(FakeLookup):
    def get(self, endpoint, params=None):
        raise RuntimeError("provider unavailable")


def test_provider_error_is_not_reported_as_no_match(tmp_path):
    path = tmp_path / "movies.db"
    make_db(path)

    report = audit_candidates(path, "not-a-real-token", limit=1, lookup_factory=FailingLookup)

    assert report["counts"]["needs_review"] == 1
    assert report["counts"]["no_match"] == 0
    assert report["results"][0]["errors"]
