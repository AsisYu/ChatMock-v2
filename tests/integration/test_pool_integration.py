"""
Integration tests for the multi-account pool feature.

Tests the full flow of:
- Multi-account login
- Account switching on rate limit
- Cooldown and recovery
- Error state handling
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import TestCase, mock
import unittest

# Add parent to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from chatmock.pool_manager import (
    AccountPool,
    Account,
    AccountTokens,
    AccountStatus,
    PoolConfig,
    PoolStorage,
    PoolService,
    NoAvailableAccountError,
    RateLimitError,
    AuthenticationError,
    UsageInfo,
    RateLimitWindow,
    reset_pool_service,
)


class TestMultiAccountLogin(TestCase):
    """Test multi-account login flow."""

    def setUp(self):
        """Create temp directory for auth files."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = PoolStorage(home_dir=self.temp_dir)
        reset_pool_service()

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_pool_service()

    def test_add_first_account(self):
        """Adding first account creates pool."""
        pool = AccountPool()
        account = Account(
            id="acc_001",
            alias="user@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )

        result = pool.add_account(account)

        self.assertTrue(result)
        self.assertEqual(len(pool.accounts), 1)
        self.assertEqual(pool.accounts[0].alias, "user@example.com")

    def test_add_second_account(self):
        """Adding second account adds to pool."""
        pool = AccountPool()

        # Add first account
        acc1 = Account(
            id="acc_001",
            alias="first@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        pool.add_account(acc1)

        # Add second account
        acc2 = Account(
            id="acc_002",
            alias="second@example.com",
            tokens=AccountTokens(
                id_token="id_002",
                access_token="access_002",
                refresh_token="refresh_002",
                account_id="acc_002",
            ),
        )
        result = pool.add_account(acc2)

        self.assertTrue(result)
        self.assertEqual(len(pool.accounts), 2)

    def test_prevent_duplicate_account(self):
        """Duplicate accounts are rejected."""
        pool = AccountPool()

        acc1 = Account(
            id="acc_001",
            alias="first@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        pool.add_account(acc1)

        # Try to add same account again
        acc1_dup = Account(
            id="acc_001",
            alias="duplicate@example.com",
            tokens=AccountTokens(
                id_token="id_dup",
                access_token="access_dup",
                refresh_token="refresh_dup",
                account_id="acc_001",
            ),
        )
        result = pool.add_account(acc1_dup)

        self.assertFalse(result)
        self.assertEqual(len(pool.accounts), 1)
        self.assertEqual(pool.accounts[0].alias, "first@example.com")


class TestAccountSwitching(TestCase):
    """Test account switching on rate limit."""

    def setUp(self):
        self.pool = AccountPool()
        reset_pool_service()

        # Add two accounts
        self.acc1 = Account(
            id="acc_001",
            alias="first@example.com",
            priority=1,
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        self.acc2 = Account(
            id="acc_002",
            alias="second@example.com",
            priority=5,
            tokens=AccountTokens(
                id_token="id_002",
                access_token="access_002",
                refresh_token="refresh_002",
                account_id="acc_002",
            ),
        )
        self.pool.add_account(self.acc1)
        self.pool.add_account(self.acc2)

    def tearDown(self):
        reset_pool_service()

    def test_select_highest_priority(self):
        """Selects account with highest priority."""
        # With both available, should prefer acc1 (priority 1)
        selected = self.pool.get_available_account()
        self.assertIsNotNone(selected)

        # Higher priority account should be selected more often
        # (weighted selection, so not guaranteed, but very likely with this difference)
        selections = {"acc_001": 0, "acc_002": 0}
        for _ in range(100):
            acc = self.pool.get_available_account()
            selections[acc.id] += 1

        # acc1 should be selected more often due to higher priority
        self.assertGreater(selections["acc_001"], selections["acc_002"])

    def test_switch_on_rate_limit(self):
        """Switches to next account when rate limited."""
        # Put acc1 in cooldown
        self.pool.record_request_failure(
            "acc_001",
            RateLimitError("Rate limit exceeded", reset_after=3600)
        )

        # Should select acc2 now
        selected = self.pool.get_available_account()
        self.assertEqual(selected.id, "acc_002")

    def test_switch_on_high_usage(self):
        """Switches when usage exceeds threshold."""
        # Set high usage on acc1
        self.acc1.usage = UsageInfo(
            primary=RateLimitWindow(used_percent=96.0)
        )

        # Record success triggers cooldown check
        self.pool.record_request_success("acc_001", self.acc1.usage)

        # acc1 should be in cooldown
        self.assertEqual(self.acc1.status, AccountStatus.COOLDOWN)

        # Should select acc2
        selected = self.pool.get_available_account()
        self.assertEqual(selected.id, "acc_002")


class TestCooldownRecovery(TestCase):
    """Test cooldown and recovery behavior."""

    def setUp(self):
        self.pool = AccountPool()
        reset_pool_service()

        self.acc = Account(
            id="acc_001",
            alias="test@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        self.pool.add_account(self.acc)

    def tearDown(self):
        reset_pool_service()

    def test_cooldown_expiry(self):
        """Account recovers after cooldown expires."""
        # Put in cooldown for 1 second
        self.pool.record_request_failure(
            "acc_001",
            RateLimitError("Rate limit", reset_after=1)
        )

        self.assertEqual(self.acc.status, AccountStatus.COOLDOWN)
        self.assertIsNotNone(self.acc.cooldown_until)

        # Manually set cooldown_until to past (simulating time passage)
        self.acc.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Update cooldowns
        self.pool._update_cooldowns()

        # Should be ready now
        self.assertEqual(self.acc.status, AccountStatus.READY)

        # Should be available
        selected = self.pool.get_available_account()
        self.assertEqual(selected.id, "acc_001")

    def test_cooldown_triggers_at_threshold(self):
        """Cooldown triggers when usage exceeds threshold."""
        config = PoolConfig(cooldown_threshold=90.0)
        pool = AccountPool(config=config)

        acc = Account(
            id="acc_001",
            alias="test@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        pool.add_account(acc)

        # Set usage at 91%
        usage = UsageInfo(primary=RateLimitWindow(used_percent=91.0))
        pool.record_request_success("acc_001", usage)

        # Should be in cooldown
        self.assertEqual(acc.status, AccountStatus.COOLDOWN)


class TestErrorStateHandling(TestCase):
    """Test error state handling."""

    def setUp(self):
        self.pool = AccountPool(config=PoolConfig(max_consecutive_failures=2))
        reset_pool_service()

        self.acc = Account(
            id="acc_001",
            alias="test@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        self.pool.add_account(self.acc)

    def tearDown(self):
        reset_pool_service()

    def test_auth_failure_sets_error(self):
        """Authentication failure sets error status."""
        self.pool.record_request_failure(
            "acc_001",
            AuthenticationError("Invalid token")
        )

        self.assertEqual(self.acc.status, AccountStatus.ERROR)
        self.assertIn("Authentication", self.acc.diagnostics.error_reason)

    def test_consecutive_failures_set_error(self):
        """Consecutive failures set error status."""
        # Record failures
        self.pool.record_request_failure("acc_001", Exception("Error 1"))
        self.assertEqual(self.acc.diagnostics.consecutive_failures, 1)

        self.pool.record_request_failure("acc_001", Exception("Error 2"))
        self.assertEqual(self.acc.diagnostics.consecutive_failures, 2)

        # Should now be in error state
        self.assertEqual(self.acc.status, AccountStatus.ERROR)

    def test_success_resets_failure_count(self):
        """Success resets consecutive failure count."""
        # Record a failure
        self.pool.record_request_failure("acc_001", Exception("Error"))
        self.assertEqual(self.acc.diagnostics.consecutive_failures, 1)

        # Record success
        self.pool.record_request_success("acc_001")

        self.assertEqual(self.acc.diagnostics.consecutive_failures, 0)
        self.assertIsNone(self.acc.diagnostics.error_reason)


class TestPersistence(TestCase):
    """Test pool persistence."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = PoolStorage(home_dir=self.temp_dir)
        reset_pool_service()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_pool_service()

    def test_save_and_load(self):
        """Pool can be saved and loaded."""
        # Create and save pool
        pool = AccountPool()
        acc = Account(
            id="acc_001",
            alias="test@example.com",
            priority=3,
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        pool.add_account(acc)
        self.storage.save_pool(pool)

        # Load pool
        loaded = self.storage.load_pool()

        self.assertEqual(len(loaded.accounts), 1)
        self.assertEqual(loaded.accounts[0].id, "acc_001")
        self.assertEqual(loaded.accounts[0].alias, "test@example.com")
        self.assertEqual(loaded.accounts[0].priority, 3)

    def test_checksum_verification(self):
        """Checksum prevents corruption."""
        pool = AccountPool()
        acc = Account(
            id="acc_001",
            alias="test@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        pool.add_account(acc)
        self.storage.save_pool(pool)

        # Corrupt the file
        auth_path = Path(self.temp_dir) / "auth.json"
        with open(auth_path, "r") as f:
            data = json.load(f)

        data["accounts"][0]["id"] = "corrupted"

        with open(auth_path, "w") as f:
            json.dump(data, f)

        # Should fail verification
        with self.assertRaises(ValueError) as ctx:
            self.storage.load_pool()

        self.assertIn("Checksum", str(ctx.exception))


class TestThreadSafety(TestCase):
    """Test thread safety of pool operations."""

    def setUp(self):
        self.pool = AccountPool()
        reset_pool_service()

    def tearDown(self):
        reset_pool_service()

    def test_concurrent_selection(self):
        """Concurrent account selection is safe."""
        # Add accounts
        for i in range(5):
            acc = Account(
                id=f"acc_{i:03d}",
                alias=f"account{i}@example.com",
                tokens=AccountTokens(
                    id_token=f"id_{i}",
                    access_token=f"access_{i}",
                    refresh_token=f"refresh_{i}",
                    account_id=f"acc_{i:03d}",
                ),
            )
            self.pool.add_account(acc)

        # Concurrent selections
        results = []
        errors = []

        def select_account():
            try:
                acc = self.pool.get_available_account()
                results.append(acc.id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=select_account) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 100)

    def test_concurrent_modification(self):
        """Concurrent modification is safe."""
        # Add account
        acc = Account(
            id="acc_001",
            alias="test@example.com",
            tokens=AccountTokens(
                id_token="id_001",
                access_token="access_001",
                refresh_token="refresh_001",
                account_id="acc_001",
            ),
        )
        self.pool.add_account(acc)

        def modify_account():
            for _ in range(10):
                self.pool.record_request_success("acc_001")
                self.pool.record_request_failure("acc_001", Exception("test"))

        threads = [threading.Thread(target=modify_account) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Account should still be in valid state
        self.assertIsNotNone(self.pool.get_account_by_id("acc_001"))


if __name__ == "__main__":
    unittest.main()