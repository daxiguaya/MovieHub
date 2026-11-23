"""Small process-local TTL cache; no Redis dependency is required."""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
from collections import OrderedDict
from typing import Any, Callable


class CacheManager:
    def __init__(self, max_entries: int = 512, default_ttl: int = 300) -> None:
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> Any:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        lifetime = self.default_ttl if ttl is None else max(1, int(ttl))
        with self._lock:
            self._items[key] = (time.monotonic() + lifetime, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


cache_manager = CacheManager()


def _make_key(prefix: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    stable_args = []
    for value in args:
        # SQLAlchemy sessions are request-scoped and must not fragment cache keys.
        if hasattr(value, "execute") and hasattr(value, "query"):
            continue
        stable_args.append(repr(value))
    stable_kwargs = tuple(sorted((key, repr(value)) for key, value in kwargs.items()))
    return repr((prefix, tuple(stable_args), stable_kwargs))


def cached(prefix: str, ttl: int = 300) -> Callable:
    """Cache sync or async function results by their non-session arguments."""
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _make_key(prefix, args, kwargs)
                value = cache_manager.get(key)
                if value is not None:
                    return value
                result = await func(*args, **kwargs)
                cache_manager.set(key, result, ttl)
                return result
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(prefix, args, kwargs)
            value = cache_manager.get(key)
            if value is not None:
                return value
            result = func(*args, **kwargs)
            cache_manager.set(key, result, ttl)
            return result
        return sync_wrapper
    return decorator
