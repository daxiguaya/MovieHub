"""Enrich annual-chart movies from their already-linked TMDB IDs.

Read-only dry-run is the default. --apply creates and verifies a SQLite backup,
then fills only empty metadata fields. Existing Douban ratings/ranks and all
non-empty metadata are preserved. Overview text is handled by the dedicated
TMDB synopsis importer.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import (
    Chart, ChartItem, ChartSnapshot, Genre, Movie, MovieGenre,
    MovieMetadataProvenance, MovieRegion, Region, SessionLocal, get_db_path,
)
from app.metadata_constants import VALID_GENRES, VALID_REGIONS

ANNUAL_SLUGS = (
    "annual-2025-chinese-movies",
    "annual-2025-international-movies",
    "annual-2025-hidden-gems",
    "annual-2025-chinese-tv",
)
COUNTRY_NAMES = {
    "CN": "中国大陆", "HK": "中国香港", "TW": "中国台湾",
    "US": "美国", "GB": "英国", "JP": "日本", "KR": "韩国",
    "FR": "法国", "DE": "德国", "IT": "意大利", "ES": "西班牙",
    "CA": "加拿大", "AU": "澳大利亚", "IN": "印度", "TH": "泰国",
    "SG": "新加坡", "MY": "马来西亚", "RU": "俄罗斯", "IR": "伊朗",
    "SE": "瑞典", "DK": "丹麦", "NO": "挪威", "FI": "芬兰",
    "IS": "冰岛", "NL": "荷兰", "BE": "比利时", "CH": "瑞士",
    "AT": "奥地利", "IE": "爱尔兰", "NZ": "新西兰", "BR": "巴西",
    "MX": "墨西哥", "AR": "阿根廷", "TR": "土耳其", "IL": "以色列",
    "EG": "埃及", "ZA": "南非", "PL": "波兰", "CZ": "捷克",
    "PT": "葡萄牙", "GR": "希腊", "VN": "越南", "PH": "菲律宾",
    "ID": "印尼", "KH": "柬埔寨", "UA": "乌克兰", "RO": "罗马尼亚",
    "HU": "匈牙利", "AE": "阿联酋",
}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == "[]"


def _normalise(value: str) -> str:
    import re
    import unicodedata
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(ch for ch in value if ch.isalnum())


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _backup(path: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_path = directory / f"movies-before-annual-tmdb-enrichment-{stamp}.sqlite3"
    if target_path.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {target_path}")
    source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(str(target_path), timeout=30)
    try:
        source.backup(target)
        target.commit()
        check = target.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("Backup integrity_check failed")
    except Exception:
        target.close()
        source.close()
        target_path.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    return target_path


async def _fetch_details(client: httpx.AsyncClient, token: str, media_type: str, tmdb_id: str) -> dict[str, Any]:
    response = await client.get(
        f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
        params={"language": "zh-CN", "append_to_response": "credits"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("id")) != tmdb_id:
        raise ValueError("TMDB response ID does not match stored ID")
    return payload


def _extract(movie: Movie, payload: dict[str, Any]) -> dict[str, Any]:
    media_type = movie.type
    title_keys = ("title", "original_title") if media_type == "movie" else ("name", "original_name")
    provider_titles = {_normalise(str(payload.get(k) or "")) for k in title_keys}
    provider_titles.discard("")
    source_title = _normalise(movie.title)
    source_original = _normalise(movie.original_title or "")
    if not ({source_title, source_original} - {""}) & provider_titles:
        raise ValueError("TMDB title identity mismatch")

    release = payload.get("release_date") if media_type == "movie" else payload.get("first_air_date")
    year = int(release[:4]) if isinstance(release, str) and len(release) >= 4 and release[:4].isdigit() else None
    original_title = payload.get("original_title") if media_type == "movie" else payload.get("original_name")
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else {}
    cast = credits.get("cast") if isinstance(credits.get("cast"), list) else []
    crew = credits.get("crew") if isinstance(credits.get("crew"), list) else []
    directors = [
        str(p.get("name")).strip() for p in crew
        if isinstance(p, dict) and p.get("job") == "Director" and p.get("name")
    ] if media_type == "movie" else [
        str(p.get("name")).strip() for p in crew
        if isinstance(p, dict) and p.get("job") in {"Director", "Executive Producer"} and p.get("name")
    ]
    existing_directors = {_normalise(x) for x in json.loads(movie.directors or "[]") if isinstance(x, str)}
    provider_directors = {_normalise(x) for x in directors}
    if existing_directors and provider_directors and not existing_directors.intersection(provider_directors):
        raise ValueError("TMDB director identity mismatch")

    actors = []
    for person in cast[:20]:
        if isinstance(person, dict) and person.get("name"):
            name = str(person["name"]).strip()
            if name and name not in actors:
                actors.append(name)
    genres_payload = payload.get("genres") if isinstance(payload.get("genres"), list) else []
    genres = sorted({
        str(g.get("name")).strip() for g in genres_payload
        if isinstance(g, dict) and g.get("name") and str(g["name"]).strip() in VALID_GENRES
    })
    countries = payload.get("production_countries") if isinstance(payload.get("production_countries"), list) else []
    regions = sorted({
        COUNTRY_NAMES[str(c.get("iso_3166_1") or "").upper()]
        for c in countries
        if isinstance(c, dict) and COUNTRY_NAMES.get(str(c.get("iso_3166_1") or "").upper()) in VALID_REGIONS
    })
    return {
        "original_title": str(original_title).strip() if original_title else None,
        "year": year,
        "actors": actors,
        "genres": genres,
        "regions": regions,
        "source_url": f"https://www.themoviedb.org/{media_type}/{movie.tmdb_id}",
    }


def _load_targets() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Movie).join(ChartItem, ChartItem.movie_id == Movie.id)
            .join(ChartSnapshot, ChartSnapshot.id == ChartItem.snapshot_id)
            .join(Chart, Chart.list_id == ChartSnapshot.list_id)
            .where(Chart.slug.in_(ANNUAL_SLUGS))
            .distinct().order_by(Movie.id)
        ).scalars().all()
        return [{
            "id": m.id, "tmdb_id": m.tmdb_id, "type": m.type, "title": m.title,
            "original_title": m.original_title, "year": m.year, "directors": m.directors,
            "actors": m.actors,
        } for m in rows if m.tmdb_id and str(m.tmdb_id).isdigit()]



def _target_object(target: dict[str, Any]):
    from types import SimpleNamespace
    return SimpleNamespace(**target)


async def _collect(targets: list[dict[str, Any]], token: str) -> tuple[list[dict[str, Any]], Counter, list[dict[str, Any]]]:
    counts: Counter = Counter()
    accepted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    limits = httpx.Limits(max_connections=6, max_keepalive_connections=4)
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(4)

        async def one(target: dict[str, Any]) -> None:
            media_type = target["type"]
            tmdb_id = str(target["tmdb_id"])
            if media_type not in {"movie", "tv"}:
                errors.append({"id": target["id"], "tmdb_id": tmdb_id, "reason": "unsupported media type"})
                counts["rejected"] += 1
                return
            async with semaphore:
                try:
                    payload = await _fetch_details(client, token, media_type, tmdb_id)
                    extracted = _extract(_target_object(target), payload)
                    accepted.append({"target": target, "metadata": extracted})
                    counts["identity_verified"] += 1
                except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    errors.append({"id": target["id"], "tmdb_id": tmdb_id, "reason": str(exc)[:240]})
                    counts["rejected"] += 1

        await asyncio.gather(*(one(target) for target in targets))
    accepted.sort(key=lambda item: item["target"]["id"])
    return accepted, counts, errors


def _apply_records(records: list[dict[str, Any]], apply: bool) -> dict[str, Any]:
    field_counts: Counter = Counter()
    changed: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with SessionLocal() as db:
        for record in records:
            target = record["target"]
            metadata = record["metadata"]
            movie = db.get(Movie, target["id"])
            if movie is None:
                field_counts["movie_missing"] += 1
                continue
            values = {
                "original_title": metadata["original_title"],
                "year": metadata["year"],
                "actors": metadata["actors"],
            }
            for field, value in values.items():
                if value is None or not _blank(getattr(movie, field)):
                    continue
                field_counts[field] += 1
                changed.append({"movie_id": movie.id, "field": field, "value": value, "source_url": metadata["source_url"]})
                if apply:
                    stored = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if field == "actors" else value
                    setattr(movie, field, stored)
                    db.add(MovieMetadataProvenance(
                        movie_id=movie.id, field_name=field, source="tmdb",
                        source_url=metadata["source_url"], observed_at=now,
                        value_sha256=_hash(value),
                    ))

            existing_genres = {assoc.genre_obj.name for assoc in movie.genres if assoc.genre_obj}
            if not existing_genres and metadata["genres"]:
                field_counts["genres"] += 1
                changed.append({"movie_id": movie.id, "field": "genres", "value": metadata["genres"], "source_url": metadata["source_url"]})
                if apply:
                    for name in metadata["genres"]:
                        genre = db.execute(select(Genre).where(Genre.name == name)).scalar_one_or_none()
                        if genre is None:
                            genre = Genre(name=name)
                            db.add(genre)
                            db.flush()
                        db.add(MovieGenre(movie_id=movie.id, genre_id=genre.id))
                    db.add(MovieMetadataProvenance(
                        movie_id=movie.id, field_name="genres", source="tmdb",
                        source_url=metadata["source_url"], observed_at=now,
                        value_sha256=_hash(metadata["genres"]),
                    ))

            existing_regions = {assoc.region_obj.name for assoc in movie.regions if assoc.region_obj}
            if not existing_regions and metadata["regions"]:
                field_counts["regions"] += 1
                changed.append({"movie_id": movie.id, "field": "regions", "value": metadata["regions"], "source_url": metadata["source_url"]})
                if apply:
                    for name in metadata["regions"]:
                        region = db.execute(select(Region).where(Region.name == name)).scalar_one_or_none()
                        if region is None:
                            region = Region(name=name)
                            db.add(region)
                            db.flush()
                        db.add(MovieRegion(movie_id=movie.id, region_id=region.id))
                    db.add(MovieMetadataProvenance(
                        movie_id=movie.id, field_name="regions", source="tmdb",
                        source_url=metadata["source_url"], observed_at=now,
                        value_sha256=_hash(metadata["regions"]),
                    ))
        if apply:
            db.commit()
        else:
            db.rollback()

    return {"field_counts": dict(sorted(field_counts.items())), "changes": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Identity-checked annual chart TMDB metadata enrichment")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true", help="Write verified missing metadata")
    args = parser.parse_args()
    apply = bool(args.apply)

    token = settings.tmdb_api_read_token or os.getenv("TMDB_API_READ_TOKEN", "")
    if not token:
        print(json.dumps({"success": False, "error": "TMDB_API_READ_TOKEN is not configured"}, ensure_ascii=False))
        return 2

    targets = _load_targets()
    if not targets:
        print(json.dumps({"success": False, "error": "No annual chart records with numeric TMDB IDs found"}, ensure_ascii=False))
        return 2

    print(f"年度榜单目标记录：{len(targets)}")
    accepted, identity_counts, errors = asyncio.run(_collect(targets, token))
    preview = _apply_records(accepted, apply=False)
    backup_path = None
    if apply and preview["changes"]:
        db_path = Path(get_db_path())
        backup_path = _backup(db_path, Path(settings.backup_dir))
        # Recalculate and commit against current DB state after the backup.
        result = _apply_records(accepted, apply=True)
    else:
        result = preview

    report = {
        "success": True,
        "mode": "apply" if apply else "dry-run",
        "target_records": len(targets),
        "identity_verified": len(accepted),
        "identity_rejected": identity_counts["rejected"],
        "identity_checks": dict(identity_counts),
        "field_counts": result["field_counts"],
        "planned_or_applied_changes": len(result["changes"]),
        "database_written": bool(apply and result["changes"]),
        "backup": str(backup_path) if backup_path else None,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
