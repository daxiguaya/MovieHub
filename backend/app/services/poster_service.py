"""Filesystem-backed poster cache with bounded retention."""

from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger("moviehub.poster_cache")
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


class PosterCacheService:
    def __init__(self) -> None:
        self.cache_dir = Path(settings.data_dir).expanduser() / "posters"

    def _ensure_dir(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_poster(self, movie_id: int) -> tuple[str, str] | None:
        if int(movie_id) < 1:
            return None
        self._ensure_dir()
        matches = sorted(self.cache_dir.glob(f"{int(movie_id)}.*"))
        for path in matches:
            if path.is_file() and path.stat().st_size > 0:
                content_type, _ = mimetypes.guess_type(path.name)
                return str(path), content_type or "application/octet-stream"
        return None

    def save_poster(self, movie_id: int, content: bytes, content_type: str) -> str:
        movie_id = int(movie_id)
        if movie_id < 1 or not content:
            raise ValueError("Invalid poster payload")
        if not content_type.startswith("image/"):
            raise ValueError("Poster content type must be an image")
        self._ensure_dir()
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ".img"
        destination = self.cache_dir / f"{movie_id}{extension}"
        fd, temp_name = tempfile.mkstemp(prefix=f".{movie_id}-", dir=self.cache_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return str(destination)

    def clear_expired_cache(self) -> int:
        self._ensure_dir()
        cutoff = time.time() - CACHE_TTL_SECONDS
        removed = 0
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                logger.warning("Unable to clean poster cache file: %s", path)
        return removed


poster_cache_service = PosterCacheService()
