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


if __name__ == "__main__":
    unittest.main()
