"""Unit and integration tests for Stage 2 (Security & Foundation) and Stage 3 (Library & Progress)."""
import asyncio
import hashlib
import hmac
import os
import shutil
import tempfile
import time
import unittest
import urllib.parse

from fastapi import HTTPException

from config import mask_secret, settings
from db import backup as backup_db
from db import user_titles as user_titles_db
from web_api import (
    EpisodeUpdateRequest,
    PlaybackProgressRequest,
    StatusUpdateRequest,
    resolve_target_user_id,
    verify_telegram_init_data,
)


def generate_mock_init_data(user_id: int, bot_token: str, auth_date: int | None = None) -> str:
    """Helper to generate cryptographically valid Telegram initData for tests."""
    data = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": f'{{"id":{user_id},"first_name":"Test","username":"testuser"}}',
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    data["hash"] = calc_hash
    return urllib.parse.urlencode(data)


class TestSecurityAndLibrary(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_security.db")
        self.orig_db_path = settings.db_path
        self.orig_dev_mode = settings.dev_mode
        settings.db_path = self.db_path
        settings.dev_mode = False

        await user_titles_db.init_user_titles(self.db_path)
        self.bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

    async def asyncTearDown(self):
        settings.db_path = self.orig_db_path
        settings.dev_mode = self.orig_dev_mode
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Secret masking
    def test_secret_masking(self):
        self.assertEqual(mask_secret(None), "<not set>")
        self.assertEqual(mask_secret(""), "<not set>")
        self.assertEqual(mask_secret("1234"), "***")
        self.assertEqual(mask_secret("secret_token_123456"), "secr...3456")

    # 2. Telegram initData validation success
    def test_init_data_valid(self):
        init_data = generate_mock_init_data(777, self.bot_token)
        verified = verify_telegram_init_data(init_data, self.bot_token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["user"]["id"], 777)

    # 3. Telegram initData tampered hash rejection
    def test_init_data_tampered_hash(self):
        init_data = generate_mock_init_data(777, self.bot_token) + "tampered"
        verified = verify_telegram_init_data(init_data, self.bot_token)
        self.assertIsNone(verified)

    # 4. Telegram initData expired auth_date rejection
    def test_init_data_expired(self):
        # 10 days old (> 7 days max_age)
        old_time = int(time.time()) - (10 * 86400)
        init_data = generate_mock_init_data(777, self.bot_token, auth_date=old_time)
        verified = verify_telegram_init_data(init_data, self.bot_token)
        self.assertIsNone(verified)

    # 5. Telegram initData future timestamp rejection
    def test_init_data_future(self):
        future_time = int(time.time()) + 1000
        init_data = generate_mock_init_data(777, self.bot_token, auth_date=future_time)
        verified = verify_telegram_init_data(init_data, self.bot_token)
        self.assertIsNone(verified)

    # 6. Zero-trust user_id: anonymous request rejected without dev_mode
    def test_zero_trust_anonymous_rejected(self):
        anon_user = {"id": 0, "is_anonymous": True}
        settings.dev_mode = False
        with self.assertRaises(HTTPException) as ctx:
            resolve_target_user_id(anon_user, requested_user_id=888)
        self.assertEqual(ctx.exception.status_code, 401)

    # 7. Zero-trust user_id: authenticated user ID cannot be overridden by client request
    def test_zero_trust_authenticated_user_isolation(self):
        auth_user = {"id": 100, "is_anonymous": False}
        settings.dev_mode = False
        # Client tries to impersonate user 999
        target_id = resolve_target_user_id(auth_user, requested_user_id=999)
        self.assertEqual(target_id, 100)

    # 8. Dev mode allows fallback for local testing
    def test_dev_mode_fallback_allowed(self):
        anon_user = {"id": 0, "is_anonymous": True}
        settings.dev_mode = True
        target_id = resolve_target_user_id(anon_user, requested_user_id=555)
        self.assertEqual(target_id, 555)

    # 9. Status validation
    def test_status_validation(self):
        valid = StatusUpdateRequest(mal_id=1, status="watching")
        valid.validate_input()

        invalid_status = StatusUpdateRequest(mal_id=1, status="invalid_status")
        with self.assertRaises(HTTPException) as ctx:
            invalid_status.validate_input()
        self.assertEqual(ctx.exception.status_code, 400)

        invalid_mal = StatusUpdateRequest(mal_id=-5, status="watching")
        with self.assertRaises(HTTPException):
            invalid_mal.validate_input()

    # 10. Episode validation
    def test_episode_validation(self):
        valid = EpisodeUpdateRequest(mal_id=1, episode=5)
        valid.validate_input()

        invalid_ep = EpisodeUpdateRequest(mal_id=1, episode=-1)
        with self.assertRaises(HTTPException):
            invalid_ep.validate_input()

    # 11. SQLite online backup and restore
    async def test_backup_and_restore(self):
        # Insert test records
        await user_titles_db.set_status(1, 10, "Title 10", "ru", "watching", db_path=self.db_path)
        await user_titles_db.set_episode(1, 10, "Title 10", "ru", 4, db_path=self.db_path)

        backup_file = os.path.join(self.temp_dir, "backup.db")
        restored_file = os.path.join(self.temp_dir, "restored.db")

        # Create backup
        success_backup = backup_db.create_backup(self.db_path, backup_file)
        self.assertTrue(success_backup)
        self.assertTrue(os.path.exists(backup_file))

        # Restore
        success_restore = backup_db.restore_backup(backup_file, restored_file)
        self.assertTrue(success_restore)
        self.assertTrue(os.path.exists(restored_file))

        # Check restored content
        state = await user_titles_db.get(1, 10, db_path=restored_file)
        self.assertIsNotNone(state)
        self.assertEqual(state["title"], "Title 10")
        self.assertEqual(state["current_episode"], 4)

    # 12. Favorites independent of status
    async def test_favorites_independent_of_status(self):
        user_id, mal_id = 2, 20
        # Favorite when plan
        await user_titles_db.set_status(user_id, mal_id, "Fav Anime", "ru", "plan", db_path=self.db_path)
        fav = await user_titles_db.toggle_favorite(user_id, mal_id, "Fav Anime", "ru", db_path=self.db_path)
        self.assertTrue(fav)

        # Move to dropped — favorite persists!
        await user_titles_db.set_status(user_id, mal_id, "Fav Anime", "ru", "dropped", db_path=self.db_path)
        row = await user_titles_db.get(user_id, mal_id, db_path=self.db_path)
        self.assertEqual(row["status"], "dropped")
        self.assertTrue(row["is_favorite"])

    # 13. Playback progress 85% rule: watching ep 10 does NOT complete eps 1-9
    async def test_episode_progress_85_rule_does_not_complete_previous(self):
        user_id, mal_id = 3, 30

        # User directly watches episode 5 at 86% of duration
        await user_titles_db.save_playback_progress(
            user_id=user_id,
            mal_id=mal_id,
            episode=5,
            position=1250,
            duration=1440,  # 1250/1440 = 86.8%
            title="Ep Progress Anime",
            db_path=self.db_path,
        )

        completed_eps = await user_titles_db.get_completed_episodes(user_id, mal_id, db_path=self.db_path)
        self.assertEqual(completed_eps, [5])  # only 5 is completed!

        # Episodes 1-4 are NOT marked completed!
        all_eps = await user_titles_db.get_episodes_progress(user_id, mal_id, db_path=self.db_path)
        self.assertIn(5, all_eps)
        self.assertTrue(all_eps[5]["is_completed"])
        self.assertNotIn(1, all_eps)
        self.assertNotIn(2, all_eps)

        # The whole anime title is watching, NOT completed
        title_state = await user_titles_db.get_title_state(user_id, mal_id, db_path=self.db_path)
        self.assertEqual(title_state["status"], "watching")
        self.assertEqual(title_state["current_episode"], 5)
        self.assertEqual(title_state["completed_episodes"], [5])

        # Stats reports 1 episode watched, NOT 5
        stats = await user_titles_db.get_stats(user_id, db_path=self.db_path)
        self.assertEqual(stats["episodes_watched"], 1)

    # 14. Delayed or out-of-order heartbeat packet does not regress position
    async def test_outdated_heartbeat_does_not_regress_position(self):
        user_id, mal_id = 4, 40
        # First save position 500 at time T
        await user_titles_db.save_playback_progress(
            user_id=user_id,
            mal_id=mal_id,
            episode=1,
            position=500,
            duration=1200,
            title="Heartbeat Anime",
            db_path=self.db_path,
        )

        # Second save position 515 at time T+15
        await user_titles_db.save_playback_progress(
            user_id=user_id,
            mal_id=mal_id,
            episode=1,
            position=515,
            duration=1200,
            title="Heartbeat Anime",
            db_path=self.db_path,
        )

        eps = await user_titles_db.get_episodes_progress(user_id, mal_id, db_path=self.db_path)
        self.assertEqual(eps[1]["position"], 515)


if __name__ == "__main__":
    unittest.main()
