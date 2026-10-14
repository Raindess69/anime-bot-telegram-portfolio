import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from utils.cache import TTLCache
from services import aggregator
from services.http_client import request_with_retry


class TestRecommendationsAndAPI(unittest.IsolatedAsyncioTestCase):

    async def test_get_recommendations_filter_and_reasons(self):
        """Verify get_recommendations filters excluded IDs, sets reason, and sorts desc."""
        mock_candidates = [
            {"mal_id": 101, "title": "Anime A", "score": "7.5"},
            {"mal_id": 102, "title": "Anime B", "score": "8.9"},
            {"mal_id": 103, "title": "Anime C", "score": "8.1"},
            {"mal_id": 104, "title": "Anime D", "score": "6.5"},
        ]

        with patch("services.aggregator.vibe_search", new=AsyncMock(return_value=(mock_candidates, False))):
            # Exclude 102 (watched)
            recs = await aggregator.get_recommendations(
                genre_slug="action",
                exclude_mal_ids={102},
                limit=10,
            )
            # Should not include 102
            ids = [r["mal_id"] for r in recs]
            self.assertNotIn(102, ids)
            self.assertIn(101, ids)
            self.assertIn(103, ids)

            # Check sorting (8.1 then 7.5 then 6.5)
            self.assertEqual(ids, [103, 101, 104])

            # Check recommendation reason contains genre
            self.assertTrue(any("action" in r["recommendation_reason"] for r in recs))

    async def test_get_recommendations_seed_title(self):
        mock_candidates = [{"mal_id": 201, "title": "Frieren", "score": "9.1"}]
        with patch("services.aggregator.vibe_search", new=AsyncMock(return_value=(mock_candidates, False))):
            recs = await aggregator.get_recommendations(
                seed_title="Sousou no Frieren",
                limit=5,
            )
            self.assertEqual(len(recs), 1)
            self.assertIn("Sousou no Frieren", recs[0]["recommendation_reason"])

    async def test_ttl_cache_coalescing(self):
        """Verify single-flight coalescing: concurrent requests only compute once."""
        cache = TTLCache(ttl_seconds=60, max_size=10)
        compute_count = 0

        async def _expensive():
            nonlocal compute_count
            compute_count += 1
            await asyncio.sleep(0.05)
            return "computed_value"

        # Launch 5 concurrent calls for the same key
        tasks = [cache.get_or_compute("same_key", _expensive) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        self.assertEqual(results, ["computed_value"] * 5)
        self.assertEqual(compute_count, 1, "Expected single-flight to compute only once")

    async def test_ttl_cache_lru_eviction(self):
        """Verify LRU eviction when max_size is exceeded."""
        cache = TTLCache(ttl_seconds=60, max_size=2)
        await cache.set("k1", "v1")
        await cache.set("k2", "v2")
        # Touch k1 so k2 becomes the LRU
        self.assertEqual(await cache.get("k1"), "v1")

        # Adding k3 should evict k2
        await cache.set("k3", "v3")
        self.assertIsNotNone(await cache.get("k1"))
        self.assertIsNone(await cache.get("k2"))
        self.assertIsNotNone(await cache.get("k3"))

    async def test_http_client_bounded_retries(self):
        """Verify request_with_retry retries on connection error and fails cleanly after max retries."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("services.http_client.get_http_client", return_value=mock_client), \
             patch("services.http_client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(httpx.ConnectError):
                await request_with_retry("GET", "https://api.example.com/data", max_retries=2)

            # Initial attempt + 2 retries = 3 calls
            self.assertEqual(mock_client.request.call_count, 3)

    async def test_http_client_retry_after(self):
        """Verify request_with_retry honors 429 Retry-After header."""
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request = AsyncMock(side_effect=[resp_429, resp_200])

        with patch("services.http_client.get_http_client", return_value=mock_client), \
             patch("services.http_client.asyncio.sleep", new=AsyncMock()):
            res = await request_with_retry("GET", "https://api.example.com/data", max_retries=1)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(mock_client.request.call_count, 2)

    async def test_health_endpoints(self):
        """Verify health check endpoints return expected status codes and payloads."""
        from web_api import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp_health = await client.get("/health")
            self.assertEqual(resp_health.status_code, 200)
            self.assertEqual(resp_health.json()["status"], "ok")

            resp_live = await client.get("/health/live")
            self.assertEqual(resp_live.status_code, 200)
            self.assertEqual(resp_live.json()["status"], "live")

            resp_ready = await client.get("/health/ready")
            self.assertEqual(resp_ready.status_code, 200)
            self.assertEqual(resp_ready.json()["status"], "ready")

    async def test_feed_endpoint_caching_and_coalescing(self):
        """Regression test: verify /api/feed caches public feed and avoids repeated upstream requests."""
        from web_api import app
        from utils.cache import feed_cache
        await feed_cache.clear()

        upstream_call_count = 0

        async def _mock_top_anime(*args, **kwargs):
            nonlocal upstream_call_count
            upstream_call_count += 1
            return [{"id": 1, "mal_id": 1, "title_ru": "Anime 1", "score": "8.5"}]

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=_mock_top_anime)):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # First request computes feed (3 categories: airing, bypopularity, None)
                resp1 = await client.get("/api/feed")
                self.assertEqual(resp1.status_code, 200)
                data1 = resp1.json()
                self.assertEqual(len(data1["airing"]), 1)
                first_calls = upstream_call_count
                self.assertGreaterEqual(first_calls, 1)

                # Second request must hit in-memory feed_cache with 0 new upstream calls
                resp2 = await client.get("/api/feed")
                self.assertEqual(resp2.status_code, 200)
                data2 = resp2.json()
                self.assertEqual(data2["airing"], data1["airing"])
                self.assertEqual(upstream_call_count, first_calls, "Feed cache should prevent repeated upstream calls")

    async def test_feed_fallback_when_shikimori_slow_or_down(self):
        """Regression test: verify /api/feed falls back to aggregator.top_anime_multi when Shikimori fails."""
        from web_api import app
        from utils.cache import feed_cache
        await feed_cache.clear()

        fallback_items = [{"id": 99, "mal_id": 99, "title_en": "Fallback Anime", "score": "9.0"}]

        # Shikimori times out / fails
        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=httpx.ReadTimeout("Shikimori read timeout"))), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(return_value=fallback_items)):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/feed")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                # Should have fallen back and populated airing/popular/top
                self.assertEqual(len(data["airing"]), 1)
                self.assertEqual(data["airing"][0]["mal_id"], 99)

    async def test_continue_watching_resilient_to_upstream_failure(self):
        """Regression test: verify continue_watching returns even if all upstream sources are unavailable."""
        from web_api import app
        from utils.cache import feed_cache
        await feed_cache.clear()

        mock_watching = [{"mal_id": 42, "title": "My Active Watch", "current_episode": 3}]

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=Exception("All upstreams dead"))), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(return_value=[])), \
             patch("db.user_titles.list_by_status", new=AsyncMock(return_value=mock_watching)):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/feed?user_id=8888")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(len(data["continue_watching"]), 1)
                self.assertEqual(data["continue_watching"][0]["mal_id"], 42)

    async def test_feed_overall_deadline_budget_on_hanging_sources(self):
        """Verify feed completes strictly within the overall deadline budget when upstreams hang."""
        from web_api import _fetch_public_feed
        import time

        async def _hanging_source(*args, **kwargs):
            await asyncio.sleep(5.0)
            return []

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=_hanging_source)), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(side_effect=_hanging_source)):
            start = time.monotonic()
            # Test with a strict 0.15s overall budget
            feed = await _fetch_public_feed(lang="ru", budget=0.15)
            elapsed = time.monotonic() - start

            # Must finish within 0.15s + small overhead tolerance (e.g. < 0.35s)
            self.assertLess(elapsed, 0.4, f"Overall deadline budget breached: {elapsed:.3f}s")
            self.assertEqual(feed["feed_state"], "error")
            self.assertIn("airing", feed["unavailable_sections"])
            self.assertIn("popular", feed["unavailable_sections"])
            self.assertIn("top", feed["unavailable_sections"])

    async def test_feed_partial_results_fast_source_preserved(self):
        """Verify that when one category finishes quickly and others hang, the fast category is preserved."""
        from web_api import _fetch_public_feed

        fast_airing = [{"id": 10, "mal_id": 10, "title_ru": "Fast Ongoing", "score": "8.0"}]

        async def _smart_mock(filter_ = None, *args, **kwargs):
            if filter_ == "airing":
                return fast_airing
            # Other categories hang
            await asyncio.sleep(5.0)
            return []

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=_smart_mock)), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(side_effect=_smart_mock)):
            feed = await _fetch_public_feed(lang="ru", budget=0.15)

            # Airing finished in time and must be preserved
            self.assertEqual(feed["airing"], fast_airing)
            self.assertEqual(feed["section_status"]["airing"], "ok")

            # Popular and top timed out
            self.assertEqual(feed["section_status"]["popular"], "timeout")
            self.assertEqual(feed["section_status"]["top"], "timeout")
            self.assertEqual(feed["feed_state"], "partial")
            self.assertIn("popular", feed["unavailable_sections"])
            self.assertIn("top", feed["unavailable_sections"])

    async def test_fallback_shares_same_deadline_budget(self):
        """Verify fallback does not get a fresh full budget after Shikimori exhausts remaining time."""
        from web_api import _fetch_public_feed
        import time

        async def _slow_shikimori(*args, **kwargs):
            # Exhausts most of the budget
            await asyncio.sleep(0.12)
            return []

        fallback_called = False
        async def _fallback_probe(*args, **kwargs):
            nonlocal fallback_called
            fallback_called = True
            await asyncio.sleep(2.0)
            return []

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=_slow_shikimori)), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(side_effect=_fallback_probe)):
            start = time.monotonic()
            feed = await _fetch_public_feed(lang="ru", budget=0.15)
            elapsed = time.monotonic() - start

            # Finished under overall budget without giving fallback a full new 0.15s
            self.assertLess(elapsed, 0.35)
            self.assertEqual(feed["feed_state"], "error")

    async def test_http_client_long_retry_after_no_early_retry(self):
        """Verify request_with_retry does not retry early if Retry-After exceeds interactive budget."""
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "30"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request = AsyncMock(return_value=resp_429)

        with patch("services.http_client.get_http_client", return_value=mock_client), \
             patch("services.http_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            res = await request_with_retry("GET", "https://api.example.com/data", max_retries=1)
            self.assertEqual(res.status_code, 429)
            # Must NOT sleep or retry early when Retry-After is 30s
            mock_sleep.assert_not_called()
            self.assertEqual(mock_client.request.call_count, 1)

    async def test_feed_total_failure_not_cached_as_success(self):
        """Verify that total feed failure is NOT cached in feed_cache for 300 seconds."""
        from web_api import app
        from utils.cache import feed_cache
        await feed_cache.clear()

        attempts = 0
        async def _flaky_top(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 3:
                # First round of 3 categories fails
                return []
            # Second round succeeds
            return [{"id": 77, "mal_id": 77, "title_ru": "Recovered Anime", "score": "8.8"}]

        with patch("services.shikimori.top_anime", new=AsyncMock(side_effect=_flaky_top)), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(return_value=[])):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # 1st request fails
                r1 = await client.get("/api/feed")
                self.assertEqual(r1.status_code, 200)
                self.assertEqual(r1.json()["feed_state"], "error")

                # Verify feed_cache does not store the total failure
                cached = await feed_cache.get("public_feed:ru")
                self.assertIsNone(cached, "Complete failure must not be cached")

                # 2nd request immediately retries upstream and succeeds
                r2 = await client.get("/api/feed")
                self.assertEqual(r2.status_code, 200)
                self.assertEqual(r2.json()["feed_state"], "ok")
                self.assertEqual(len(r2.json()["airing"]), 1)

    async def test_fallback_preserves_category_semantics(self):
        """Verify fallback preserves exact category filter semantics (airing, bypopularity, None)."""
        from web_api import _fetch_public_feed

        captured_filters = []
        async def _capture_fallback(filter_, *args, **kwargs):
            captured_filters.append(filter_)
            return [{"id": 1, "mal_id": 1, "title_en": f"Title {filter_}", "score": "8.0"}]

        with patch("services.shikimori.top_anime", new=AsyncMock(return_value=[])), \
             patch("services.aggregator.top_anime_multi", new=AsyncMock(side_effect=_capture_fallback)):
            feed = await _fetch_public_feed(lang="ru", budget=1.0)
            self.assertIn("airing", captured_filters, "Airing filter must be passed to fallback")
            self.assertIn("bypopularity", captured_filters, "Popularity filter must be passed to fallback")
            self.assertIn(None, captured_filters, "Ranked/top filter (None) must be passed to fallback")
            self.assertEqual(feed["feed_state"], "ok")

    async def test_single_flight_coalescing_clears_inflight_after_deadline(self):
        """Verify single-flight request coalescing clears in-flight future on timeout/failure."""
        cache = TTLCache(ttl_seconds=60)

        async def _hanging_calc():
            await asyncio.sleep(2.0)
            return "done"

        # Call with very short timeout
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.05):
                await cache.get_or_compute("timeout_key", _hanging_calc)

        # Allow worker task loop turn to complete cleanup
        await asyncio.sleep(0.01)

        # In-flight map must not leak or stay frozen
        self.assertNotIn("timeout_key", cache._inflight, "In-flight task must be removed after error")


if __name__ == "__main__":
    unittest.main()
