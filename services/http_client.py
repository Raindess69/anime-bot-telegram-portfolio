"""Shared asynchronous HTTP client with lifecycle management, connection pooling,
concurrency limits, bounded retries, and Retry-After support.
"""
import asyncio
import logging
from typing import Any, Mapping

import httpx

_log = logging.getLogger(__name__)

# Upstream domain concurrency limits to prevent rate limit violations
_DOMAIN_LIMIT_VALUES = {
    "shikimori.one": 5,
    "shikimori.io": 5,
    "shikimori.me": 5,
    "api.jikan.moe": 3,
    "kodikapi.com": 5,
    "api.anilibria.tv": 5,
    "graphql.anilist.co": 5,
}
_DEFAULT_LIMIT_VALUE = 10

_semaphores: dict[tuple[int, str], asyncio.Semaphore] = {}
_client_instance: httpx.AsyncClient | None = None
_client_lock: asyncio.Lock | None = None

_DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=3.0, read=5.0, write=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)


def _get_client_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def get_http_client() -> httpx.AsyncClient:
    """Returns the shared singleton httpx.AsyncClient instance."""
    global _client_instance
    if _client_instance is not None and not _client_instance.is_closed:
        return _client_instance

    lock = _get_client_lock()
    async with lock:
        if _client_instance is None or _client_instance.is_closed:
            _client_instance = httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT,
                limits=_DEFAULT_LIMITS,
                headers={"User-Agent": "EnjoyAnimeBot/2.0 (Telegram Mini App)"},
                follow_redirects=True,
            )
    return _client_instance


async def close_http_client() -> None:
    """Closes the shared HTTP client cleanly during shutdown."""
    global _client_instance
    lock = _get_client_lock()
    async with lock:
        if _client_instance is not None and not _client_instance.is_closed:
            await _client_instance.aclose()
            _client_instance = None
            _log.info("Shared HTTP client closed.")


def _get_semaphore(url: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    matched_domain = "default"
    limit_val = _DEFAULT_LIMIT_VALUE
    for domain, val in _DOMAIN_LIMIT_VALUES.items():
        if domain in url:
            matched_domain = domain
            limit_val = val
            break

    key = (loop_id, matched_domain)
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(limit_val)
    return _semaphores[key]


async def request_with_retry(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any = None,
    max_retries: int = 1,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    """Executes an HTTP request with concurrency bounds, Retry-After support, and bounded retries."""
    client = await get_http_client()
    sem = _get_semaphore(url)

    attempt = 0
    effective_timeout = timeout or _DEFAULT_TIMEOUT
    while True:
        attempt += 1
        try:
            async with sem:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json,
                    timeout=effective_timeout,
                )

            # Check 429 Too Many Requests
            if resp.status_code == 429:
                retry_after_hdr = resp.headers.get("Retry-After")
                wait_sec = 1.0
                if retry_after_hdr and retry_after_hdr.isdigit():
                    wait_sec = float(retry_after_hdr)

                # Never retry earlier than provider's Retry-After.
                # If Retry-After exceeds the interactive threshold (2.0s), do not wait and do not retry early;
                # fail fast immediately to allow callers to use fallback or cached data.
                MAX_INTERACTIVE_RETRY_AFTER = 2.0
                if attempt <= max_retries and wait_sec <= MAX_INTERACTIVE_RETRY_AFTER:
                    _log.warning("Rate limit on %s (429). Retrying after %.1fs (attempt %d/%d)", url, wait_sec, attempt, max_retries)
                    await asyncio.sleep(wait_sec)
                    continue
                _log.warning("Rate limit on %s (429) with Retry-After=%.1fs exceeds interactive budget. Skipping retry.", url, wait_sec)
                return resp

            # Bounded retry on 502/503/504
            if resp.status_code in (502, 503, 504):
                if attempt <= max_retries:
                    wait_sec = min(0.5 * (2 ** (attempt - 1)), 2.0)
                    _log.info("Upstream error %d on %s. Retrying after %.1fs", resp.status_code, url, wait_sec)
                    await asyncio.sleep(wait_sec)
                    continue
                return resp

            return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as err:
            if attempt <= max_retries:
                wait_sec = min(0.3 * attempt, 1.0)
                _log.info("Network glitch on %s (%s). Retrying after %.1fs", url, type(err).__name__, wait_sec)
                await asyncio.sleep(wait_sec)
                continue
            raise
