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

    async def test_category_endpoint_validation(self):
        """Verify /api/category/{category} validates allowed category and page/limit bounds."""
        from httpx import ASGITransport, AsyncClient
        from web_api import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Invalid category
            resp = await client.get("/api/category/unknown_category")
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Invalid category", resp.json()["detail"])

            # Invalid page bounds (page < 1)
            resp = await client.get("/api/category/airing?page=0")
            self.assertEqual(resp.status_code, 422)

            # Invalid limit bounds (limit > 50)
            resp = await client.get("/api/category/airing?limit=51")
            self.assertEqual(resp.status_code, 422)

    async def test_category_semantics_and_parameters(self):
        """Verify category endpoint passes correct filter parameters to aggregator."""
        from httpx import ASGITransport, AsyncClient
        from web_api import app

        sample_items = [{"id": 1, "mal_id": 1, "title_ru": "Anime 1", "score": "8.0"}]
        mock_get_page = AsyncMock(return_value={
            "category": "airing",
            "page": 1,
            "limit": 24,
            "items": sample_items,
            "has_more": True,
            "total": None,
            "source": "shikimori",
        })

        with patch("services.aggregator.get_category_page", new=mock_get_page):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/category/airing?page=2&limit=24")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["category"], "airing")
                mock_get_page.assert_awaited_once_with(
                    category="airing",
                    page=2,
                    limit=24,
                    preferred_source=None,
                    timeout=5.0,
                )

    async def test_category_cache_keys_distinct_by_page_limit_lang_source(self):
        """Verify different page, limit, lang, and source parameters produce distinct cache entries."""
        from utils.cache import category_cache
        from httpx import ASGITransport, AsyncClient
        from web_api import app

        await category_cache.clear()

        call_args = []
        async def _mock_page(category, page, limit, preferred_source, timeout):
            call_args.append((category, page, limit, preferred_source))
            return {
                "category": category,
                "page": page,
                "limit": limit,
                "items": [{"id": page, "mal_id": page, "title_ru": f"{category}-{page}-{limit}-{preferred_source}"}],
                "has_more": True,
                "total": None,
                "source": preferred_source or "shikimori",
            }

        with patch("services.aggregator.get_category_page", side_effect=_mock_page):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r1 = await client.get("/api/category/popular?page=1&limit=24&lang=ru")
                r2 = await client.get("/api/category/popular?page=2&limit=24&lang=ru")
                r3 = await client.get("/api/category/popular?page=1&limit=12&lang=ru")  # distinct limit
                r4 = await client.get("/api/category/popular?page=1&limit=24&lang=en")  # distinct lang
                r5 = await client.get("/api/category/popular?page=1&limit=24&lang=ru&source=jikan")  # distinct source
                r6 = await client.get("/api/category/popular?page=1&limit=24&lang=ru")  # cache hit of r1

                self.assertEqual(r1.status_code, 200)
                self.assertEqual(r2.status_code, 200)
                self.assertEqual(r3.status_code, 200)
                self.assertEqual(r4.status_code, 200)
                self.assertEqual(r5.status_code, 200)
                self.assertEqual(r6.status_code, 200)

                # r1 and r6 share key ('popular', 1, 24, None) -> called once
                self.assertEqual(call_args, [
                    ("popular", 1, 24, None),
                    ("popular", 2, 24, None),
                    ("popular", 1, 12, None),
                    ("popular", 1, 24, None),  # lang=en produces separate cache key
                    ("popular", 1, 24, "jikan"),
                ])

    async def test_category_upstream_failure_not_cached(self):
        """Verify upstream errors raise 502 and are not cached."""
        from utils.cache import category_cache
        from httpx import ASGITransport, AsyncClient
        from web_api import app

        await category_cache.clear()

        call_count = 0
        async def _mock_flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Temporary upstream crash")
            return {
                "category": "top",
                "page": 1,
                "limit": 24,
                "items": [{"id": 10, "mal_id": 10, "title_ru": "Top Anime"}],
                "has_more": False,
                "total": 10,
                "source": "anilist",
            }

        with patch("services.aggregator.get_category_page", side_effect=_mock_flaky):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r1 = await client.get("/api/category/top?page=1")
                self.assertEqual(r1.status_code, 502)

                # Verify not cached
                self.assertEqual(len(category_cache._store), 0)

                # 2nd call retries and succeeds
                r2 = await client.get("/api/category/top?page=1")
                self.assertEqual(r2.status_code, 200)
                self.assertEqual(r2.json()["items"][0]["id"], 10)

    async def test_category_provider_pinning_and_deduplication(self):
        """Verify preferred_source pins the provider and deduplicates items by ID."""
        from services import aggregator

        raw_with_duplicates = [
            {"id": 101, "shikimori_id": 101, "mal_id": 101, "title_ru": "Anime A"},
            {"id": 102, "shikimori_id": 102, "mal_id": 102, "title_ru": "Anime B"},
            {"id": 101, "shikimori_id": 101, "mal_id": 101, "title_ru": "Anime A Duplicate"},
        ]

        with patch("services.shikimori.top_anime_page", new=AsyncMock(return_value=(raw_with_duplicates, True, None))), \
             patch("services.jikan.top_anime_page", new=AsyncMock(return_value=([{"id": 999}], False, None))):
            # Initial page
            res = await aggregator.get_category_page(
                category="airing",
                page=1,
                limit=24,
                preferred_source="shikimori",
            )
            self.assertEqual(res["source"], "shikimori")
            self.assertEqual(len(res["items"]), 2, "Duplicate item 101 must be deduplicated")
            self.assertEqual([x["id"] for x in res["items"]], [101, 102])

            # If preferred_source fails, does NOT query jikan
            with patch("services.shikimori.top_anime_page", side_effect=RuntimeError("Shiki down")):
                res_failed = await aggregator.get_category_page(
                    category="airing",
                    page=2,
                    limit=24,
                    preferred_source="shikimori",
                )
                self.assertEqual(res_failed["items"], [])
                self.assertIsNone(res_failed["source"], "Must not switch provider when pinned")

    async def test_shikimori_top_anime_page_partial_filtered_preserves_continuation(self):
        """Case 1: Raw page is full (24 items), but after filtering missing posters 15 remain.

        Continuation must NOT be lost (has_more=True).
        """
        from services import shikimori
        from unittest.mock import MagicMock

        # 15 items with valid posters, 9 with missing poster
        raw_page_1 = [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "https://shiki/poster.jpg"}}
            for i in range(1, 16)
        ] + [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "https://shiki/missing_original.jpg"}}
            for i in range(16, 25)
        ]
        raw_page_2 = [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "https://shiki/poster.jpg"}}
            for i in range(25, 49)
        ]

        def _mock_get(url, params=None, timeout=None, max_retries=1):
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            if params and params.get("page") == 1:
                mock_resp.json.return_value = raw_page_1
            elif params and params.get("page") == 2:
                mock_resp.json.return_value = raw_page_2
            else:
                mock_resp.json.return_value = []
            return mock_resp

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get)):
            items, has_more, total = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 24, "All 24 valid titles must remain with fallback posters for missing images")
            self.assertTrue(has_more, "has_more must be True when upstream page was full and page 2 exists")
            # Verify 15 have real poster and 9 have fallback poster SVG
            real_posters = [x for x in items if x["image_url"] != shikimori.FALLBACK_POSTER_SVG]
            fallback_posters = [x for x in items if x["image_url"] == shikimori.FALLBACK_POSTER_SVG]
            self.assertEqual(len(real_posters), 15)
            self.assertEqual(len(fallback_posters), 9)

    async def test_shikimori_top_anime_page_subsequent_page_new_titles_and_no_skips(self):
        """Case 2: Page 2 returns 24 distinct items with 0 ID intersection and no offset skips."""
        from services import shikimori
        from unittest.mock import MagicMock

        # Page 1: 24 raw, all valid titles (15 with poster, 9 missing)
        raw_page_1 = [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "https://shiki/poster.jpg"}}
            for i in range(1, 16)
        ] + [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "missing"}}
            for i in range(16, 25)
        ]
        # Page 2: 24 raw (offset 24..47), all valid titles (20 with poster, 4 missing)
        raw_page_2 = [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "https://shiki/poster.jpg"}}
            for i in range(25, 45)
        ] + [
            {"id": i, "name": f"Airing {i}", "russian": f"Аниме {i}", "image": {"original": "missing"}}
            for i in range(45, 49)
        ]
        # Page 3: probe
        raw_page_3 = [{"id": 49, "name": "Airing 49", "image": {"original": "poster.jpg"}}]

        def _mock_get(url, params=None, timeout=None, max_retries=1):
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            p = params.get("page") if params else 1
            if p == 1:
                mock_resp.json.return_value = raw_page_1
            elif p == 2:
                mock_resp.json.return_value = raw_page_2
            elif p == 3:
                mock_resp.json.return_value = raw_page_3
            else:
                mock_resp.json.return_value = []
            return mock_resp

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get)):
            items_p1, has_more_p1, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            items_p2, has_more_p2, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=2)

            ids_p1 = {x["shikimori_id"] for x in items_p1}
            ids_p2 = {x["shikimori_id"] for x in items_p2}

            self.assertEqual(len(ids_p1), 24)
            self.assertEqual(len(ids_p2), 24)
            self.assertEqual(ids_p1 & ids_p2, set(), "Page 1 and Page 2 must have zero intersecting IDs")
            self.assertTrue(has_more_p1)
            self.assertTrue(has_more_p2)

    async def test_shikimori_top_anime_page_real_end_of_catalog(self):
        """Case 3: Real end of catalog detection (both via raw < limit and empty probe)."""
        from services import shikimori
        from unittest.mock import MagicMock

        # Subcase 3A: Upstream returns fewer than limit (e.g. 10 < 24) -> immediate has_more=False
        resp_3a = MagicMock()
        resp_3a.is_success = True
        resp_3a.status_code = 200
        resp_3a.json.return_value = [
            {"id": i, "name": f"Airing {i}", "image": {"original": "poster.jpg"}}
            for i in range(1, 11)
        ]
        with patch("services.shikimori._get", new=AsyncMock(return_value=resp_3a)):
            items, has_more, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 10)
            self.assertFalse(has_more, "has_more must be False when upstream returned fewer than limit")

        # Subcase 3B: Upstream returns exactly limit (24), but probe for next page returns empty list []
        def _mock_get_3b(url, params=None, timeout=None, max_retries=1):
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            p = params.get("page") if params else 1
            if p == 1:
                mock_resp.json.return_value = [{"id": i, "name": f"Airing {i}", "image": {"original": "poster.jpg"}} for i in range(1, 25)]
            else:
                mock_resp.json.return_value = []  # Page 2 empty!
            return mock_resp

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get_3b)):
            items, has_more, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 24)
            self.assertFalse(has_more, "has_more must be False when probe of next page returns empty list")

    async def test_shikimori_top_anime_page_probe_error_does_not_cut_off_catalog(self):
        """Case 4: Probe error/timeout on next page must NOT cut off catalog (optimistic has_more=True)."""
        import httpx
        from services import shikimori
        from unittest.mock import MagicMock

        def _mock_get(url, params=None, timeout=None, max_retries=1):
            p = params.get("page") if params else 1
            if p == 1:
                mock_resp = MagicMock()
                mock_resp.is_success = True
                mock_resp.status_code = 200
                mock_resp.json.return_value = [{"id": i, "name": f"Airing {i}", "image": {"original": "poster.jpg"}} for i in range(1, 25)]
                return mock_resp
            else:
                # Probe times out or crashes
                raise httpx.ConnectTimeout("Next page probe timeout")

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get)):
            items, has_more, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 24)
            self.assertTrue(has_more, "has_more must remain True when next-page probe times out/errors")

    async def test_shikimori_top_anime_page_empty_after_filter_not_end_of_catalog(self):
        """Case 5: Empty page after filtering truly invalid IDs does not falsely report end of catalog."""
        from services import aggregator, shikimori
        from unittest.mock import MagicMock

        # Page 1: 24 raw items, but ALL have truly invalid IDs (None or <= 0)
        raw_page_1 = [
            {"id": None, "name": f"Airing {i}", "image": {"original": "poster.jpg"}}
            for i in range(1, 25)
        ]
        raw_page_2 = [
            {"id": i, "name": f"Airing {i}", "image": {"original": "valid_poster.jpg"}}
            for i in range(25, 49)
        ]

        def _mock_get(url, params=None, timeout=None, max_retries=1):
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            p = params.get("page") if params else 1
            if p == 1:
                mock_resp.json.return_value = raw_page_1
            else:
                mock_resp.json.return_value = raw_page_2
            return mock_resp

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get)):
            items, has_more, _ = await shikimori.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 0, "All items with invalid IDs filtered out locally")
            self.assertTrue(has_more, "has_more must be True because upstream page was full and page 2 exists")

            # Check aggregator level
            res = await aggregator.get_category_page(category="airing", page=1, limit=24)
            self.assertEqual(res["items"], [])
            self.assertTrue(res["has_more"], "Aggregator must preserve has_more=True despite empty valid items")
            self.assertEqual(res["source"], "shikimori")

    async def test_jikan_top_anime_page_authoritative_pagination(self):
        """Case 6: Jikan uses authoritative pagination.has_next_page, not local valid items count."""
        from services import jikan
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "pagination": {
                "has_next_page": True,
                "current_page": 1,
                "items": {"count": 18, "total": 500, "per_page": 24},
            },
            # 18 valid items
            "data": [{"mal_id": i, "title": f"Anime {i}", "score": 8.0} for i in range(1, 19)],
        }

        with patch("services.jikan._get_with_retry", new=AsyncMock(return_value=mock_resp)):
            items, has_more, total = await jikan.top_anime_page(filter_="airing", limit=24, page=1)
            self.assertEqual(len(items), 18)
            self.assertTrue(has_more, "has_more must follow pagination.has_next_page=True")
            self.assertEqual(total, 500)

    async def test_top_anime_does_not_probe_next_page(self):
        """Verify top_anime (used by feed) calls Shikimori exactly once without page+1 probe."""
        from services import shikimori
        from unittest.mock import MagicMock

        calls = []
        def _mock_get(url, params=None, timeout=None, max_retries=1):
            calls.append(params.get("page") if params else 1)
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            # Return full page of 10 items
            mock_resp.json.return_value = [
                {"id": i, "name": f"Anime {i}", "image": {"original": "poster.jpg"}}
                for i in range(1, 11)
            ]
            return mock_resp

        with patch("services.shikimori._get", new=AsyncMock(side_effect=_mock_get)):
            # 1. top_anime() should ONLY fetch page 1, never probe page 2
            items = await shikimori.top_anime(filter_="airing", limit=10, page=1)
            self.assertEqual(len(items), 10)
            self.assertEqual(calls, [1], "top_anime must make exactly 1 call without probing page+1")

            # 2. In contrast, top_anime_page(probe_next=True) should make 2 calls (page 1 + probe page 2)
            calls.clear()
            items_page, has_more, _ = await shikimori.top_anime_page(filter_="airing", limit=10, page=1, probe_next=True)
            self.assertEqual(len(items_page), 10)
            self.assertEqual(calls, [1, 2], "top_anime_page must probe page+1 when probe_next=True")

    def test_shikimori_is_valid_anime_validation_rules(self):
        """Validate that titles with valid IDs and names are preserved regardless of poster/description."""
        from services.shikimori import _is_valid_anime

        # 1. No image block -> VALID
        self.assertTrue(_is_valid_anime({"id": 101, "name": "Solo Leveling", "russian": "Поднятие уровня"}))
        # 2. image = null -> VALID
        self.assertTrue(_is_valid_anime({"id": 102, "name": "Solo Leveling 2", "image": None}))
        # 3. image without original -> VALID
        self.assertTrue(_is_valid_anime({"id": 103, "name": "Solo Leveling 3", "image": {"preview": "/preview.jpg"}}))
        # 4. original contains 'missing' -> VALID
        self.assertTrue(_is_valid_anime({"id": 104, "name": "Solo Leveling 4", "image": {"original": "/assets/missing/original.jpg"}}))
        # 5. Correct poster -> VALID
        self.assertTrue(_is_valid_anime({"id": 105, "name": "Solo Leveling 5", "image": {"original": "https://shikimori.one/poster.jpg"}}))
        # 6. Title without description -> VALID
        self.assertTrue(_is_valid_anime({"id": 106, "name": "No Description Anime", "description": None, "description_html": None}))
        # 7. Russian title only, no english name -> VALID
        self.assertTrue(_is_valid_anime({"id": 107, "name": None, "russian": "Только русское"}))
        # 8. English name only, no russian -> VALID
        self.assertTrue(_is_valid_anime({"id": 108, "name": "English Only", "russian": None}))

        # Invalid cases: truly invalid ID (None, <=0, non-integer) or empty titles -> REJECT
        self.assertFalse(_is_valid_anime({"id": None, "name": "Invalid ID"}))
        self.assertFalse(_is_valid_anime({"id": 0, "name": "Zero ID"}))
        self.assertFalse(_is_valid_anime({"id": -10, "name": "Negative ID"}))
        self.assertFalse(_is_valid_anime({"id": "not_an_int", "name": "String ID"}))
        self.assertFalse(_is_valid_anime({"id": 109, "name": "", "russian": ""}))
        self.assertFalse(_is_valid_anime({"id": 110, "name": "   ", "russian": "\t\n"}))
        self.assertFalse(_is_valid_anime(None))
        self.assertFalse(_is_valid_anime("not a dict"))
        self.assertFalse(_is_valid_anime([]))

    def test_shikimori_image_url_normalization_and_fallback(self):
        """Verify normalization of poster URLs and fallback SVG generation."""
        from services.shikimori import _image_url, FALLBACK_POSTER_SVG

        # Missing or null image
        self.assertEqual(_image_url({}), FALLBACK_POSTER_SVG)
        self.assertEqual(_image_url({"image": None}), FALLBACK_POSTER_SVG)
        self.assertEqual(_image_url({"image": {}}), FALLBACK_POSTER_SVG)
        self.assertEqual(_image_url({"image": {"original": None, "preview": None}}), FALLBACK_POSTER_SVG)
        self.assertEqual(_image_url({"image": {"original": "https://shikimori.one/assets/missing/original.jpg"}}), FALLBACK_POSTER_SVG)
        self.assertEqual(_image_url({"image": {"original": "/assets/globals/missing.jpg"}}), FALLBACK_POSTER_SVG)

        # Domain rewriting shikimori.one -> shikimori.io
        self.assertEqual(
            _image_url({"image": {"original": "https://shikimori.one/system/animes/original/1.jpg"}}),
            "https://shikimori.io/system/animes/original/1.jpg"
        )
        self.assertEqual(
            _image_url({"image": {"original": "http://shikimori.one/system/animes/original/2.jpg"}}),
            "https://shikimori.io/system/animes/original/2.jpg"
        )

        # Relative path gets prefixed with https://shikimori.io
        self.assertEqual(
            _image_url({"image": {"original": "/system/animes/original/3.jpg"}}),
            "https://shikimori.io/system/animes/original/3.jpg"
        )

        # Other external absolute URL preserved
        self.assertEqual(
            _image_url({"image": {"original": "https://cdn.myanimelist.net/images/anime/4.jpg"}}),
            "https://cdn.myanimelist.net/images/anime/4.jpg"
        )

    async def test_shikimori_top_anime_page_24_valid_titles_with_14_missing_posters_returns_all_24(self):
        """Diagnosed scenario: 24 raw items with 14 missing posters must return ALL 24, not 10."""
        from services import shikimori
        from unittest.mock import MagicMock

        # 10 items with valid posters, 14 with various missing poster formats
        raw_items = [
            {"id": i, "name": f"Valid Poster Anime {i}", "image": {"original": f"https://shiki/poster_{i}.jpg"}}
            for i in range(1, 11)
        ] + [
            # 5 items with "missing" in original
            {"id": i, "name": f"Missing URL Anime {i}", "image": {"original": "https://shiki/assets/missing/original.jpg"}}
            for i in range(11, 16)
        ] + [
            # 5 items with image = None
            {"id": i, "name": f"Null Image Anime {i}", "image": None}
            for i in range(16, 21)
        ] + [
            # 4 items with empty image dict
            {"id": i, "name": f"Empty Image Anime {i}", "image": {}}
            for i in range(21, 25)
        ]
        self.assertEqual(len(raw_items), 24)

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = raw_items

        with patch("services.shikimori._get", new=AsyncMock(return_value=mock_resp)):
            items, has_more, total = await shikimori.top_anime_page(filter_="airing", limit=24, page=1, probe_next=False)

            # Must return all 24 items, NOT 10!
            self.assertEqual(len(items), 24, f"Expected 24 items, got {len(items)}")

            # 10 items have valid external poster URLs
            valid_posters = [x for x in items if x["image_url"] != shikimori.FALLBACK_POSTER_SVG]
            self.assertEqual(len(valid_posters), 10)

            # 14 items have FALLBACK_POSTER_SVG
            fallback_posters = [x for x in items if x["image_url"] == shikimori.FALLBACK_POSTER_SVG]
            self.assertEqual(len(fallback_posters), 14)

            # None have undefined, null or empty strings
            for x in items:
                self.assertIsNotNone(x["image_url"])
                self.assertNotIn(x["image_url"], ["undefined", "null", ""])

    async def test_shikimori_search_and_seasonal_preserve_posterless_titles(self):
        """Verify search, seasonal and search_advanced also retain titles without posters."""
        from services import shikimori
        from unittest.mock import MagicMock

        raw_items = [
            {"id": 1, "name": "Has Poster", "image": {"original": "https://shiki/p1.jpg"}},
            {"id": 2, "name": "No Poster", "image": {"original": "missing"}},
            {"id": 3, "name": "Null Poster", "image": None},
        ]
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = raw_items

        with patch("services.shikimori._get", new=AsyncMock(return_value=mock_resp)):
            # Search
            search_res = await shikimori.search("test", limit=10)
            self.assertEqual(len(search_res), 3)
            self.assertEqual(search_res[1]["image_url"], shikimori.FALLBACK_POSTER_SVG)
            self.assertEqual(search_res[2]["image_url"], shikimori.FALLBACK_POSTER_SVG)

            # Seasonal
            seasonal_res = await shikimori.seasonal(2026, "spring", limit=10)
            self.assertEqual(len(seasonal_res), 3)
            self.assertEqual(seasonal_res[1]["image_url"], shikimori.FALLBACK_POSTER_SVG)

            # Search advanced
            adv_res = await shikimori.search_advanced(limit=10)
            self.assertEqual(len(adv_res), 3)
            self.assertEqual(adv_res[1]["image_url"], shikimori.FALLBACK_POSTER_SVG)


if __name__ == "__main__":
    unittest.main()
