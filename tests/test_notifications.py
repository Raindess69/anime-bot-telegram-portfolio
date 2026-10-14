"""Comprehensive unit and integration test suite for Push Notifications Backend (Task P1.1).

Covers all 30 mandatory checks:
- Recipient qualification (watching, favorite, plan, completed, dropped).
- Deduplication and single upstream query per title.
- Outbox persistence, transactionality, and baseline tracking.
- Network and source error handling, flood control (RetryAfter), and user blocking (Forbidden).
- Deep-link formats, tunnel rotation reactivity, and HTML security.
- Migrations on new and legacy databases, and background lifecycle cancellation.
"""
import asyncio
import html
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message

from config import settings
from db import outbox as outbox_db
from db import subscriptions as subs_db
from db import user_titles as user_titles_db
from db import users as users_db
from services import scheduler


class TestPushNotificationsBackend(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_bot.db")
        self.orig_db_path = settings.db_path
        settings.db_path = self.db_path

        # Initialize test database
        await users_db.init_db(self.db_path)
        # Initialize subscriptions schema manually for test db
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(subs_db._SCHEMA_V2)
            await db.executescript(user_titles_db._SCHEMA)
            await db.commit()
        await outbox_db.init_outbox(self.db_path)

        # Mock bot
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock(return_value=MagicMock(spec=Message))
        scheduler._telegram_flood_until = 0.0

        # Default mini app URL patch
        self.mock_url = "https://test-tunnel.pinggy.link"

    async def asyncTearDown(self):
        scheduler._telegram_flood_until = 0.0
        settings.db_path = self.orig_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. watching receives event
    async def test_01_watching_receives_event(self):
        user_id, mal_id = 101, 10
        await user_titles_db.set_status(user_id, mal_id, "Anime 10", "ru", "watching")
        # Baseline at 5
        await outbox_db.set_tracked_title_baseline(mal_id, 5, "Anime 10", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [5, 6], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["user_id"], user_id)
        self.assertEqual(pending[0]["episode"], 6)

    # 2. favorite receives event
    async def test_02_favorite_receives_event(self):
        user_id, mal_id = 102, 11
        await user_titles_db.set_status(user_id, mal_id, "Anime 11", "ru", "plan")
        await user_titles_db.toggle_favorite(user_id, mal_id, "Anime 11", "ru")
        await outbox_db.set_tracked_title_baseline(mal_id, 2, "Anime 11", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [2, 3], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(pending[0]["user_id"], user_id)
        self.assertEqual(pending[0]["episode"], 3)

    # 3. watching + favorite receives single event
    async def test_03_watching_plus_favorite_receives_single_event(self):
        user_id, mal_id = 103, 12
        await user_titles_db.set_status(user_id, mal_id, "Anime 12", "ru", "watching")
        await user_titles_db.toggle_favorite(user_id, mal_id, "Anime 12", "ru")
        await outbox_db.set_tracked_title_baseline(mal_id, 1, "Anime 12", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [1, 2], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(len(pending), 1)

    # 4. plan without favorite receives no event
    async def test_04_plan_without_favorite_receives_no_event(self):
        user_id, mal_id = 104, 13
        await user_titles_db.set_status(user_id, mal_id, "Anime 13", "ru", "plan")
        await outbox_db.set_tracked_title_baseline(mal_id, 1, "Anime 13", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [1, 2], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 0)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(len(pending), 0)

    # 5. completed without favorite receives no event
    async def test_05_completed_without_favorite_receives_no_event(self):
        user_id, mal_id = 105, 14
        await user_titles_db.set_status(user_id, mal_id, "Anime 14", "ru", "completed")
        await outbox_db.set_tracked_title_baseline(mal_id, 12, "Anime 14", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [12, 13], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 0)

    # 6. completed + favorite receives event
    async def test_06_completed_with_favorite_receives_event(self):
        user_id, mal_id = 106, 15
        await user_titles_db.set_status(user_id, mal_id, "Anime 15", "ru", "completed")
        await user_titles_db.toggle_favorite(user_id, mal_id, "Anime 15", "ru")
        await outbox_db.set_tracked_title_baseline(mal_id, 12, "Anime 15", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [12, 13], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)

    # 7. dropped + favorite receives event
    async def test_07_dropped_with_favorite_receives_event(self):
        user_id, mal_id = 107, 16
        await user_titles_db.set_status(user_id, mal_id, "Anime 16", "ru", "dropped")
        await user_titles_db.toggle_favorite(user_id, mal_id, "Anime 16", "ru")
        await outbox_db.set_tracked_title_baseline(mal_id, 4, "Anime 16", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [4, 5], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)

    # 8. Multiple users watching same title: single query per title per cycle
    async def test_08_multiple_users_single_probe_query(self):
        mal_id = 108
        for uid in [201, 202, 203, 204]:
            await user_titles_db.set_status(uid, mal_id, "Shared Anime", "ru", "watching")
        await outbox_db.set_tracked_title_baseline(mal_id, 1, "Shared Anime", db_path=self.db_path)

        mock_probe = AsyncMock(return_value={"episodes": [1, 2], "name": "Anilibria"})
        with patch("services.scheduler._probe_anilibria", mock_probe), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        # 4 users each get an event
        self.assertEqual(enqueued, 4)
        # But probe is queried exactly ONCE for this title
        self.assertEqual(mock_probe.call_count, 1)

    # 9. New episode creates event
    async def test_09_new_episode_creates_event(self):
        user_id, mal_id = 109, 19
        await user_titles_db.set_status(user_id, mal_id, "Anime 19", "ru", "watching")
        await outbox_db.set_tracked_title_baseline(mal_id, 7, "Anime 19", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [7, 8], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(pending[0]["episode"], 8)

    # 10. Repeat cycle does not duplicate event
    async def test_10_repeat_cycle_does_not_duplicate_event(self):
        user_id, mal_id = 110, 20
        await user_titles_db.set_status(user_id, mal_id, "Anime 20", "ru", "watching")
        await outbox_db.set_tracked_title_baseline(mal_id, 1, "Anime 20", db_path=self.db_path)

        mock_p = AsyncMock(return_value={"episodes": [1, 2], "name": "Anilibria"})
        with patch("services.scheduler._probe_anilibria", mock_p), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued_1 = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)
            enqueued_2 = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued_1, 1)
        self.assertEqual(enqueued_2, 0)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(len(pending), 1)

    # 11. First observation establishes baseline without sending historical episodes
    async def test_11_first_run_does_not_spam_old_episodes(self):
        user_id, mal_id = 111, 21
        await user_titles_db.set_status(user_id, mal_id, "Ongoing 21", "ru", "watching")

        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": list(range(1, 25)), "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        # Baseline set to 24, 0 notifications enqueued
        self.assertEqual(enqueued, 0)
        tracked = await outbox_db.get_tracked_title(mal_id, db_path=self.db_path)
        self.assertIsNotNone(tracked)
        self.assertEqual(tracked["last_known_episode"], 24)

    # 12. Gaps in episode numbering do not fabricate missing episodes
    async def test_12_numbering_gaps_not_filled_with_fake_episodes(self):
        user_id, mal_id = 112, 22
        await user_titles_db.set_status(user_id, mal_id, "Anime 22", "ru", "watching")
        await outbox_db.set_tracked_title_baseline(mal_id, 10, "Anime 22", db_path=self.db_path)

        # Episode 11 missing; only 12 is available
        with patch("services.scheduler._probe_anilibria", AsyncMock(return_value={"episodes": [10, 12], "name": "Anilibria"})), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual([p["episode"] for p in pending], [12])

    # 13. Source error does not reset baseline
    async def test_13_source_error_does_not_reset_baseline(self):
        mal_id = 23
        await outbox_db.set_tracked_title_baseline(mal_id, 15, "Anime 23", db_path=self.db_path)

        with patch("services.scheduler._probe_anilibria", AsyncMock(side_effect=Exception("Timeout"))), \
             patch("services.scheduler._probe_kodik", AsyncMock(side_effect=Exception("Connection refused"))), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        tracked = await outbox_db.get_tracked_title(mal_id, db_path=self.db_path)
        self.assertEqual(tracked["last_known_episode"], 15)

    # 14. Failure in one title does not block processing of others
    async def test_14_single_title_error_does_not_block_others(self):
        await user_titles_db.set_status(114, 24, "Broken Title", "ru", "watching")
        await user_titles_db.set_status(115, 25, "Working Title", "ru", "watching")
        await outbox_db.set_tracked_title_baseline(24, 1, "Broken Title", anilibria_code="broken", db_path=self.db_path)
        await outbox_db.set_tracked_title_baseline(25, 1, "Working Title", anilibria_code="working", db_path=self.db_path)

        async def mock_anilibria(code):
            if code == "broken":
                raise RuntimeError("500 Internal Server Error")
            return {"episodes": [1, 2], "name": "Anilibria"}

        with patch("services.scheduler._probe_anilibria", side_effect=mock_anilibria), \
             patch("services.scheduler._probe_kodik", AsyncMock(return_value=None)), \
             patch("services.scheduler._probe_yummy", AsyncMock(return_value=None)):
            enqueued = await scheduler.check_new_episodes(self.bot, db_path=self.db_path)

        self.assertEqual(enqueued, 1)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(pending[0]["mal_id"], 25)

    # 15. Successful dispatch transitions event to sent
    async def test_15_successful_dispatch_marks_sent(self):
        user_id, mal_id = 116, 26
        await user_titles_db.set_status(user_id, mal_id, "Anime 26", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [2], [user_id], "Anime 26", db_path=self.db_path)

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 1)
        self.assertEqual(self.bot.send_message.call_count, 1)
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, sent_at FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "sent")
        self.assertIsNotNone(row[1])

    # 16. Transient error schedules retry with increased attempt count
    async def test_16_transient_error_allows_retry(self):
        user_id, mal_id = 117, 27
        await user_titles_db.set_status(user_id, mal_id, "Anime 27", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [2], [user_id], "Anime 27", db_path=self.db_path)

        self.bot.send_message = AsyncMock(side_effect=Exception("Telegram connection timeout"))

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 0)
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, attempts, next_attempt_at FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "pending")
        self.assertEqual(row[1], 1)
        self.assertGreater(row[2], int(time.time()))

    # 17. TelegramRetryAfter is respected
    async def test_17_retry_after_respected(self):
        user_id, mal_id = 118, 28
        await user_titles_db.set_status(user_id, mal_id, "Anime 28", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [2], [user_id], "Anime 28", db_path=self.db_path)

        retry_err = TelegramRetryAfter(method=MagicMock(), message="Flood wait", retry_after=45)
        self.bot.send_message = AsyncMock(side_effect=retry_err)

        before = int(time.time())
        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, next_attempt_at, last_error FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "pending")
        self.assertGreaterEqual(row[1], before + 45)
        self.assertIn("Flood control", row[2])

    # 18. Forbidden halts retry and marks recipient blocked without wiping library
    async def test_18_forbidden_stops_infinite_retry(self):
        user_id, mal_id = 119, 29
        await user_titles_db.set_status(user_id, mal_id, "Anime 29", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [2], [user_id], "Anime 29", db_path=self.db_path)

        forbidden_err = TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked by the user")
        self.bot.send_message = AsyncMock(side_effect=forbidden_err)

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        # Check status is failed (no retry)
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
            async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)) as cur:
                u_row = await cur.fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(u_row[0], 1)

        # User's library progress is still intact!
        user_item = await user_titles_db.get(user_id, mal_id)
        self.assertIsNotNone(user_item)
        self.assertEqual(user_item["title"], "Anime 29")

    # 19. Restart recovers stale processing events
    async def test_19_restart_recovers_uncompleted_processing(self):
        user_id, mal_id = 120, 30
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [3], [user_id], "Anime 30", db_path=self.db_path)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        event_id = pending[0]["id"]

        # Simulate process crash while claiming
        claimed = await outbox_db.claim_event_for_processing(event_id, db_path=self.db_path)
        self.assertTrue(claimed)

        # Call recovery
        recovered = await outbox_db.recover_stale_processing(db_path=self.db_path)
        self.assertEqual(recovered, 1)

        # Event is pending again
        pending_after = await outbox_db.fetch_pending_events(db_path=self.db_path)
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["id"], event_id)

    # 20. Atomic claim prevents parallel execution collision
    async def test_20_parallel_dispatch_no_duplicate_pickup(self):
        user_id, mal_id = 121, 31
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Anime 31", db_path=self.db_path)
        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        event_id = pending[0]["id"]

        first_claim = await outbox_db.claim_event_for_processing(event_id, db_path=self.db_path)
        second_claim = await outbox_db.claim_event_for_processing(event_id, db_path=self.db_path)

        self.assertTrue(first_claim)
        self.assertFalse(second_claim)

    # 21. Subscription cancellation before send cancels delivery
    async def test_21_unsubscribe_before_send_cancels_delivery(self):
        user_id, mal_id = 122, 32
        await user_titles_db.set_status(user_id, mal_id, "Anime 32", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Anime 32", db_path=self.db_path)

        # User drops the anime before the dispatcher runs
        await user_titles_db.set_status(user_id, mal_id, "Anime 32", "ru", "dropped")

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 0)
        self.assertEqual(self.bot.send_message.call_count, 0)

        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "cancelled")

    # 22. New recipient does not receive old outbox events created before tracking
    async def test_22_new_recipient_does_not_receive_old_queue(self):
        user_a, user_b, mal_id = 123, 124, 33
        # user_a was watching when ep 5 came out
        await user_titles_db.set_status(user_a, mal_id, "Anime 33", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [5], [user_a], "Anime 33", db_path=self.db_path)

        # user_b starts watching later
        await user_titles_db.set_status(user_b, mal_id, "Anime 33", "ru", "watching")

        pending = await outbox_db.fetch_pending_events(db_path=self.db_path)
        recipients = [p["user_id"] for p in pending]
        self.assertIn(user_a, recipients)
        self.assertNotIn(user_b, recipients)

    # 23. Actual URL dynamically used after tunnel rotation
    async def test_23_actual_url_used_after_tunnel_rotation(self):
        user_id, mal_id = 125, 34
        await user_titles_db.set_status(user_id, mal_id, "Anime 34", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [4], [user_id], "Anime 34", db_path=self.db_path)

        # Tunnel rotated to fresh link
        rotated_url = "https://fresh-tunnel-99.pinggy.link"
        with patch("handlers.commands.get_mini_app_url", return_value=rotated_url):
            await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(self.bot.send_message.call_count, 1)
        kwargs = self.bot.send_message.call_args.kwargs
        reply_markup = kwargs.get("reply_markup")
        self.assertIsInstance(reply_markup, InlineKeyboardMarkup)
        button_url = reply_markup.inline_keyboard[0][0].web_app.url
        self.assertIn(rotated_url, button_url)

    # 24. Missing Mini App URL does not send broken button
    async def test_24_missing_url_does_not_send_broken_button(self):
        user_id, mal_id = 126, 35
        await user_titles_db.set_status(user_id, mal_id, "Anime 35", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Anime 35", db_path=self.db_path)

        # URL is empty
        with patch("handlers.commands.get_mini_app_url", return_value=""):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 0)
        self.assertEqual(self.bot.send_message.call_count, 0)

        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, attempts, last_error FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "pending")
        self.assertIn("not available", row[2])

    # 25. HTML special characters in title are safely escaped
    async def test_25_title_special_chars_safe(self):
        user_id, mal_id = 127, 36
        dangerous_title = "Attack on Titan <Season 4> & 'Special' \"Edition\""
        await user_titles_db.set_status(user_id, mal_id, dangerous_title, "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], dangerous_title, db_path=self.db_path)

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        kwargs = self.bot.send_message.call_args.kwargs
        sent_text = kwargs.get("text")
        self.assertNotIn("<Season 4>", sent_text)
        self.assertIn("&lt;Season 4&gt;", sent_text)

    # 26. startapp=w_{mal_id}_{episode} format preserved
    async def test_26_startapp_format_preserved(self):
        url = scheduler.build_watch_url(555, 12)
        with patch("handlers.commands.get_mini_app_url", return_value="https://myapp.com"):
            url = scheduler.build_watch_url(555, 12)
        self.assertEqual(url, "https://myapp.com?startapp=w_555_12#w_555_12")

    # 27. Legacy database baseline migration supported
    async def test_27_new_db_and_old_schema_supported(self):
        # Create legacy schema without outbox
        legacy_db_path = os.path.join(self.temp_dir, "legacy.db")
        import aiosqlite
        async with aiosqlite.connect(legacy_db_path) as db:
            await db.execute(
                """CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    mal_id INTEGER,
                    title TEXT,
                    last_episode INTEGER,
                    created_at INTEGER
                )"""
            )
            await db.execute(
                "INSERT INTO subscriptions (user_id, mal_id, title, last_episode, created_at) VALUES (1, 999, 'Old Title', 24, 1600000000)"
            )
            await db.commit()

        # Run outbox initialization
        await outbox_db.init_outbox(legacy_db_path)

        # Baseline was migrated from last_episode
        tracked = await outbox_db.get_tracked_title(999, db_path=legacy_db_path)
        self.assertIsNotNone(tracked)
        self.assertEqual(tracked["last_known_episode"], 24)

    # 28. Repeated migration execution is idempotent and safe
    async def test_28_repeated_migration_safe(self):
        for _ in range(5):
            await outbox_db.init_outbox(self.db_path)
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 'v3_outbox'") as cur:
                count = (await cur.fetchone())[0]
        self.assertEqual(count, 1)

    # 29. Existing library entries and progress are unaffected
    async def test_29_existing_library_preserved(self):
        user_id, mal_id = 129, 77
        await user_titles_db.set_status(user_id, mal_id, "Preserved Anime", "ru", "watching")
        await user_titles_db.set_episode(user_id, mal_id, "Preserved Anime", "ru", 15)

        # Run outbox migrations and checks
        await outbox_db.init_outbox(self.db_path)
        await outbox_db.set_tracked_title_baseline(mal_id, 15, "Preserved Anime", db_path=self.db_path)

        item = await user_titles_db.get(user_id, mal_id)
        self.assertEqual(item["status"], "watching")
        self.assertEqual(item["current_episode"], 15)

    # 30. Clean cancellation of background scheduler task
    async def test_30_clean_cancellation_of_scheduler_task(self):
        task = asyncio.create_task(scheduler.run_periodic_check(self.bot, db_path=self.db_path))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    # 31. Returning user clears is_blocked on active interaction (P1.1-R)
    async def test_31_returning_user_clears_blocked_flag(self):
        user_id = 199
        await users_db.set_user_blocked(user_id, True, db_path=self.db_path)
        self.assertTrue(await users_db.is_user_blocked(user_id, db_path=self.db_path))

        # User interacts: sets language
        await users_db.set_lang(user_id, "ru", db_path=self.db_path)
        self.assertFalse(await users_db.is_user_blocked(user_id, db_path=self.db_path))

    # 32. Lease timeout recovery resets stale events but keeps active ones (P1.1-R)
    async def test_32_lease_timeout_recovery_stale_vs_fresh(self):
        mal_id = 99
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1, 2], [301, 302], "Lease Test", db_path=self.db_path)
        events = await outbox_db.fetch_pending_events(db_path=self.db_path)
        ev1_id, ev2_id = events[0]["id"], events[1]["id"]

        # Claim both
        await outbox_db.claim_event_for_processing(ev1_id, db_path=self.db_path)
        await outbox_db.claim_event_for_processing(ev2_id, db_path=self.db_path)

        # Make ev1 stale (claimed 600s ago)
        import aiosqlite
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE notification_outbox SET claimed_at = ? WHERE id = ?", (now - 600, ev1_id))
            await db.commit()

        # Recover with 300s timeout: ev1 should recover, ev2 (fresh) must stay in processing
        recovered = await outbox_db.recover_stale_processing(timeout_seconds=300, db_path=self.db_path)
        self.assertEqual(recovered, 1)

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, status FROM notification_outbox WHERE id IN (?, ?)", (ev1_id, ev2_id)) as cur:
                statuses = {row[0]: row[1] for row in await cur.fetchall()}
        self.assertEqual(statuses[ev1_id], "pending")
        self.assertEqual(statuses[ev2_id], "processing")

    # 33. Flood control pause pauses subsequent queue dispatching (P1.1-R)
    async def test_33_flood_control_pauses_dispatch(self):
        user_id, mal_id = 133, 98
        await user_titles_db.set_status(user_id, mal_id, "Flood Pause Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Flood Pause Anime", db_path=self.db_path)

        # Trigger flood pause
        retry_err = TelegramRetryAfter(method=MagicMock(), message="Flood wait", retry_after=60)
        self.bot.send_message = AsyncMock(side_effect=retry_err)

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        # Dispatcher is now paused: immediate follow-up call returns 0 without calling Telegram
        self.bot.send_message.reset_mock()
        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)
        self.assertEqual(delivered, 0)
        self.assertEqual(self.bot.send_message.call_count, 0)
        scheduler._telegram_flood_until = 0.0  # reset for subsequent tests

    # 34. Absence of tunnel URL does not consume Telegram delivery attempts and does not fail event
    async def test_34_missing_tunnel_does_not_consume_attempts(self):
        user_id, mal_id = 134, 99
        await user_titles_db.set_status(user_id, mal_id, "Tunnel Defer Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Tunnel Defer Anime", db_path=self.db_path)

        # Dispatch with tunnel URL returning None (tunnel down)
        with patch("handlers.commands.get_mini_app_url", return_value=None):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 0)
        self.assertEqual(self.bot.send_message.call_count, 0)

        # Check DB state: attempts MUST remain 0, status MUST remain 'pending' (not failed!)
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, attempts, claimed_at FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "pending")
        self.assertEqual(row[1], 0, "Delivery attempts must not be consumed when tunnel is unavailable")
        self.assertEqual(row[2], 0, "Claimed timestamp must be reset to 0")

    # 35. Fencing token: stale worker cannot overwrite new owner's result after re-claim
    async def test_35_fencing_token_prevents_stale_worker_overwrite(self):
        user_id, mal_id = 135, 100
        await user_titles_db.set_status(user_id, mal_id, "Fencing Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Fencing Anime", db_path=self.db_path)

        events = await outbox_db.fetch_pending_events(limit=1, db_path=self.db_path)
        ev_id = events[0]["id"]

        # Worker A claims event -> generation 1
        claim_a = await outbox_db.claim_event_for_processing(ev_id, db_path=self.db_path)
        self.assertGreater(claim_a, 0)

        # Simulate Worker A hang and lease recovery
        await outbox_db.recover_stale_processing(timeout_seconds=0, db_path=self.db_path)

        # Worker B re-claims event -> generation 2 (claim_b > claim_a guaranteed by generation counter!)
        claim_b = await outbox_db.claim_event_for_processing(ev_id, db_path=self.db_path)
        self.assertGreater(claim_b, claim_a, "Generation counter must increment across claims")

        # Now stale Worker A wakes up and attempts to mark event sent with old claim_a
        success_a = await outbox_db.mark_event_sent(ev_id, claim_token=claim_a, db_path=self.db_path)
        self.assertFalse(success_a, "Stale worker A must not be allowed to mark event sent")

        # Worker B completes with valid claim_b
        success_b = await outbox_db.mark_event_sent(ev_id, claim_token=claim_b, db_path=self.db_path)
        self.assertTrue(success_b, "Current owner worker B must succeed")

        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, claim_token FROM notification_outbox WHERE id = ?", (ev_id,)) as cur:
                row = await cur.fetchone()
        self.assertEqual(row[0], "sent")
        self.assertEqual(row[1], claim_b)

    # 36. TelegramRetryAfter resets claimed event to pending (does not leave it hanging in processing)
    async def test_36_retry_after_resets_processing_to_pending(self):
        user_id, mal_id = 136, 101
        await user_titles_db.set_status(user_id, mal_id, "RetryAfter Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "RetryAfter Anime", db_path=self.db_path)

        retry_err = TelegramRetryAfter(method=MagicMock(), message="Flood wait", retry_after=15)
        self.bot.send_message = AsyncMock(side_effect=retry_err)

        with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
            delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)

        self.assertEqual(delivered, 0)

        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, claimed_at, next_attempt_at FROM notification_outbox WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "pending", "Event must be reset to pending on RetryAfter")
        self.assertEqual(row[1], 0, "claimed_at must be reset to 0 so lease is not held")
        self.assertGreater(row[2], int(time.time()), "next_attempt_at must be scheduled in the future")
        scheduler._telegram_flood_until = 0.0  # cleanup

    # 37. Full URL generator and WebApp keyboard contract (P1.1-R URL verification)
    async def test_37_full_url_and_keyboard_contract(self):
        mal_id, episode = 44511, 7
        tunnel_base = "https://safe-demo-tunnel.pinggy.link"

        with patch("handlers.commands.get_mini_app_url", return_value=tunnel_base):
            # 1. Verify exact full URL structure
            full_url = scheduler.build_watch_url(mal_id, episode)
            expected_url = f"{tunnel_base}?startapp=w_{mal_id}_{episode}#w_{mal_id}_{episode}"
            self.assertEqual(full_url, expected_url)

            # 2. Verify button type and keyboard structure
            kb = scheduler.build_watch_keyboard(mal_id, episode, lang="ru")
            self.assertIsNotNone(kb)
            self.assertEqual(len(kb.inline_keyboard), 1)
            btn = kb.inline_keyboard[0][0]

            # Button MUST be of type web_app with WebAppInfo(url=full_url), NOT a regular url button
            self.assertIsNotNone(btn.web_app, "Watch button must have web_app field set")
            self.assertEqual(btn.web_app.url, expected_url)
            self.assertIsNone(btn.url, "Watch button must not use external url field")
            self.assertIn("Смотреть", btn.text)

        # 3. Insecure or missing tunnel must reject generation
        with patch("handlers.commands.get_mini_app_url", return_value="http://insecure.tunnel"):
            self.assertIsNone(scheduler.build_watch_url(mal_id, episode))
            self.assertIsNone(scheduler.build_watch_keyboard(mal_id, episode))

        with patch("handlers.commands.get_mini_app_url", return_value=None):
            self.assertIsNone(scheduler.build_watch_url(mal_id, episode))
            self.assertIsNone(scheduler.build_watch_keyboard(mal_id, episode))

    # 38. Active processing claim rejection: Worker B cannot claim active event before lease expiry
    async def test_38_active_lease_claim_rejected_and_token_unchanged(self):
        user_id, mal_id = 138, 102
        await user_titles_db.set_status(user_id, mal_id, "Active Lease Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Active Lease Anime", db_path=self.db_path)

        events = await outbox_db.fetch_pending_events(limit=1, db_path=self.db_path)
        ev_id = events[0]["id"]

        # 1. Worker A claims event -> receives claim_token > 0 and status becomes 'processing'
        claim_a = await outbox_db.claim_event_for_processing(ev_id, db_path=self.db_path)
        self.assertGreater(claim_a, 0, "Worker A must successfully claim pending event")

        # 2. Lease has NOT expired: Worker B attempts to claim the same event
        claim_b = await outbox_db.claim_event_for_processing(ev_id, db_path=self.db_path)
        self.assertEqual(claim_b, 0, "Worker B claim must be rejected when event is in active processing")

        # 3. Verify DB state: claim_token of active owner does NOT change, status remains 'processing'
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, claim_token, claimed_at FROM notification_outbox WHERE id = ?", (ev_id,)) as cur:
                row = await cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "processing", "Status must remain processing")
        self.assertEqual(row[1], claim_a, "claim_token must NOT change after rejected claim attempt")
        self.assertGreater(row[2], 0, "claimed_at lease timestamp must remain active")

    # 39. Safe launch flag: DISABLE_OUTBOX_DISPATCH skips sending without touching queue
    async def test_39_disable_outbox_dispatch_flag(self):
        user_id, mal_id = 139, 103
        await user_titles_db.set_status(user_id, mal_id, "Disabled Dispatch Anime", "ru", "watching")
        await outbox_db.enqueue_events_and_update_baseline(mal_id, [1], [user_id], "Disabled Dispatch Anime", db_path=self.db_path)

        events_before = await outbox_db.fetch_pending_events(limit=10, db_path=self.db_path)
        self.assertEqual(len(events_before), 1)

        # 1. With disable_outbox_dispatch=True -> 0 delivered, bot.send_message NOT called
        from config import settings
        orig_setting = settings.disable_outbox_dispatch
        try:
            settings.disable_outbox_dispatch = True
            with patch("handlers.commands.get_mini_app_url", return_value="https://test.link"):
                delivered = await scheduler.dispatch_pending_outbox(self.bot, db_path=self.db_path)
            self.assertEqual(delivered, 0, "No notifications delivered when disabled")
            self.assertEqual(self.bot.send_message.call_count, 0, "Telegram Bot API must not be called")

            # Queue remains intact and pending
            events_after = await outbox_db.fetch_pending_events(limit=10, db_path=self.db_path)
            self.assertEqual(len(events_after), 1, "Queue must remain pending and untouched")
            self.assertEqual(events_after[0]["status"], "pending")
        finally:
            settings.disable_outbox_dispatch = orig_setting


if __name__ == "__main__":
    unittest.main()



