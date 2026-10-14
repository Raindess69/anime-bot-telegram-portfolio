"""Shared asynchronous HTTP client with lifecycle management, connection pooling,
concurrency limits, bounded retries, and Retry-After support.
"""
import asyncio
import logging
from typing import Any, Mapping

import httpx

_log = logging.getLogger(__name__)

# Upstream domain concurrency limits to prevent rate limit violations
_DOMAIN_LIMITS = {
    "shikimori.one": asyncio.Semaphore(5),
    "shikimori.io": asyncio.Semaphore(5),
    "shikimori.me": asyncio.Semaphore(5),
    "api.jikan.moe": asyncio.Semaphore(3),
    "kodikapi.com": asyncio.Semaphore(5),
    "api.anilibria.tv": asyncio.Semaphore(5),
    "graphql.anilist.co": asyncio.Semaphore(5),
}
_DEFAULT_SEMAPHORE = asyncio.Semaphore(10)

_client_instance: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()

_DEFAULT_TIMEOUT = httpx.Timeout(12.0, connect=5.0, read=10.0, write=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)


async def get_http_client() -> httpx.AsyncClient:
    """Returns the shared singleton httpx.AsyncClient instance."""
    global _client_instance
    if _client_instance is not None and not _client_instance.is_closed:
        return _client_instance

    async with _client_lock:
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
    async with _client_lock:
        if _client_instance is not None and not _client_instance.is_closed:
            await _client_instance.aclose()
            _client_instance = None
            _log.info("Shared HTTP client closed.")


def _get_semaphore(url: str) -> asyncio.Semaphore:
    for domain, sem in _DOMAIN_LIMITS.items():
        if domain in url:
            return sem
    return _DEFAULT_SEMAPHORE


async def request_with_retry(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any = None,
    max_retries: int = 2,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    """Executes an HTTP request with concurrency bounds, Retry-After support, and bounded retries."""
    client = await get_http_client()
    sem = _get_semaphore(url)

    attempt = 0
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
                    timeout=timeout or _DEFAULT_TIMEOUT,
                )

            # Check 429 Too Many Requests
            if resp.status_code == 429 and attempt <= max_retries:
                retry_after = resp.headers.get("Retry-After")
                wait_sec = 2.0
                if retry_after and retry_after.isdigit():
                    wait_sec = min(float(retry_after), 10.0)
                _log.warning("Rate limit on %s (429). Retrying after %.1fs (attempt %d/%d)", url, wait_sec, attempt, max_retries)
                await asyncio.sleep(wait_sec)
                continue

            # Bounded retry on 502/503/504
            if resp.status_code in (502, 503, 504) and attempt <= max_retries:
                wait_sec = 1.0 * (2 ** (attempt - 1))
                _log.info("Upstream error %d on %s. Retrying after %.1fs", resp.status_code, url, wait_sec)
                await asyncio.sleep(wait_sec)
                continue

            return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as err:
            if attempt <= max_retries:
                wait_sec = 0.8 * attempt
                _log.info("Network glitch on %s (%s). Retrying after %.1fs", url, type(err).__name__, wait_sec)
                await asyncio.sleep(wait_sec)
                continue
            raise
