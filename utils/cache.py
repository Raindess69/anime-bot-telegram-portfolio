"""Thread-safe and async-safe LRU/TTL Cache with request coalescing (single-flight).

Guarantees:
- Hard memory bound: enforces max_size with LRU eviction.
- Time-based TTL expiration per entry.
- Request coalescing: identical concurrent requests share a single in-flight task,
  preventing duplicate upstream API stampedes.
- Zero PII: cache keys only index public parameters (query, lang, page, filters).
"""
import asyncio
import time
from collections import OrderedDict
from typing import Any, Callable, Coroutine


class TTLCache:
    def __init__(self, ttl_seconds: int = 600, max_size: int = 500):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock: asyncio.Lock | None = None
        self._hits = 0
        self._misses = 0

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_unlocked(self, key: str) -> Any | None:
        if key not in self._store:
            self._misses += 1
            return None
        expires_at, value = self._store[key]
        if expires_at < time.monotonic():
            del self._store[key]
            self._misses += 1
            return None
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def _set_unlocked(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic() + self._ttl, value)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    async def get(self, key: str) -> Any | None:
        async with self._get_lock():
            return self._get_unlocked(key)

    async def set(self, key: str, value: Any) -> None:
        async with self._get_lock():
            self._set_unlocked(key, value)

    async def get_or_compute(
        self,
        key: str,
        coro_fn: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """Coalesces identical concurrent requests. Only one coroutine executes; others await result."""
        lock = self._get_lock()
        async with lock:
            val = self._get_unlocked(key)
            if val is not None:
                return val

            if key in self._inflight:
                fut = self._inflight[key]
            else:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                self._inflight[key] = fut

                async def _worker():
                    try:
                        computed = await coro_fn()
                        async with lock:
                            self._set_unlocked(key, computed)
                        if not fut.done():
                            fut.set_result(computed)
                    except Exception as err:
                        if not fut.done():
                            fut.set_exception(err)
                    finally:
                        async with lock:
                            self._inflight.pop(key, None)

                asyncio.create_task(_worker())

        return await asyncio.shield(fut)

    async def clear(self) -> None:
        async with self._get_lock():
            self._store.clear()
            self._inflight.clear()

    @property
    def stats(self) -> dict:
        return {
            "size": len(self._store),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
        }


search_cache = TTLCache(ttl_seconds=600, max_size=500)
feed_cache = TTLCache(ttl_seconds=300, max_size=100)
vibe_cache = TTLCache(ttl_seconds=900, max_size=200)
