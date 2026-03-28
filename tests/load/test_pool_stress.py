"""
Load tests for the multi-account pool.

Tests concurrent access patterns to ensure:
- No race conditions
- Thread safety
- Acceptable performance under load
"""

import threading
import time
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase
import unittest

# Add parent to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from chatmock.pool_manager import (
    AccountPool,
    Account,
    AccountTokens,
    PoolConfig,
    PoolStorage,
    PoolService,
    NoAvailableAccountError,
    reset_pool_service,
)


class TestPoolStress(TestCase):
    """Stress tests for pool under concurrent load."""

    def setUp(self):
        """Create pool with 5 accounts."""
        self.pool = AccountPool()
        reset_pool_service()

        # Create 5 test accounts
        for i in range(5):
            acc = Account(
                id=f"acc_{i:03d}",
                alias=f"account{i}@example.com",
                priority=i + 1,
                tokens=AccountTokens(
                    id_token=f"id_{i}",
                    access_token=f"access_{i}",
                    refresh_token=f"refresh_{i}",
                    account_id=f"acc_{i:03d}",
                ),
            )
            self.pool.add_account(acc)

    def tearDown(self):
        reset_pool_service()

    def test_100_concurrent_selections(self):
        """100 concurrent requests with 5 accounts."""
        results = []
        errors = []
        lock = threading.Lock()

        def select_and_record():
            try:
                for _ in range(10):  # Each thread does 10 selections
                    acc = self.pool.get_available_account()
                    with lock:
                        results.append(acc.id)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Create 10 threads, each doing 10 selections = 100 total
        threads = [threading.Thread(target=select_and_record) for _ in range(10)]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start

        # Verify results
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 100, f"Expected 100 results, got {len(results)}")

        # All accounts should have been used
        used_accounts = set(results)
        self.assertGreaterEqual(len(used_accounts), 3, "At least 3 accounts should be used")

        # Performance check: should complete in reasonable time
        self.assertLess(elapsed, 5.0, f"Test took too long: {elapsed}s")

    def test_concurrent_read_write(self):
        """Concurrent reads and writes don't cause race conditions."""
        errors = []

        def read_operations():
            try:
                for _ in range(50):
                    self.pool.get_pool_status()
                    self.pool.list_account_statuses()
            except Exception as e:
                errors.append(f"Read error: {e}")

        def write_operations():
            try:
                for i in range(50):
                    acc_id = f"acc_{i % 5:03d}"
                    self.pool.record_request_success(acc_id)
                    self.pool.record_request_failure(acc_id, Exception("test"))
            except Exception as e:
                errors.append(f"Write error: {e}")

        # Run readers and writers concurrently
        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=read_operations))
            threads.append(threading.Thread(target=write_operations))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors: {errors}")

    def test_no_deadlock_under_load(self):
        """No deadlock occurs under heavy load."""
        completed = [0]
        lock = threading.Lock()

        def mixed_operations():
            try:
                for _ in range(20):
                    # Mix of operations
                    self.pool.get_available_account()
                    self.pool.get_pool_status()
                    self.pool.record_request_success("acc_000")
                    acc = self.pool.get_account_by_id("acc_001")
                    if acc:
                        _ = acc.to_dict()
                with lock:
                    completed[0] += 1
            except Exception:
                pass

        # 20 threads doing mixed operations
        threads = [threading.Thread(target=mixed_operations) for _ in range(20)]

        start = time.time()
        for t in threads:
            t.start()

        # Wait with timeout (deadlock detection)
        for t in threads:
            t.join(timeout=10.0)

        elapsed = time.time() - start

        # All threads should complete without deadlock
        self.assertEqual(completed[0], 20, f"Only {completed[0]}/20 threads completed")
        self.assertLess(elapsed, 10.0, "Possible deadlock detected")

    def test_account_selection_distribution(self):
        """Account selection follows priority weights."""
        selections = {}

        def select_many():
            for _ in range(100):
                acc = self.pool.get_available_account()
                with threading.Lock():
                    selections[acc.id] = selections.get(acc.id, 0) + 1

        threads = [threading.Thread(target=select_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Total selections = 500
        total = sum(selections.values())
        self.assertEqual(total, 500)

        # Higher priority accounts should be selected more
        # acc_000 has priority 1, acc_004 has priority 5
        self.assertGreater(selections.get("acc_000", 0), selections.get("acc_004", 0))


class TestPersistenceStress(TestCase):
    """Stress tests for persistence layer."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = PoolStorage(home_dir=self.temp_dir)
        reset_pool_service()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_pool_service()

    def test_concurrent_saves(self):
        """Concurrent saves don't corrupt data."""
        errors = []

        def save_pool(i):
            try:
                pool = AccountPool()
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
                pool.add_account(acc)
                self.storage.save_pool(pool)
            except Exception as e:
                errors.append(str(e))

        # 10 concurrent save operations
        threads = [threading.Thread(target=save_pool, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        # Note: Some saves may overwrite others, but no corruption should occur
        self.assertEqual(len(errors), 0, f"Errors: {errors}")

        # Final load should succeed
        pool = self.storage.load_pool()
        self.assertIsNotNone(pool)


class TestPerformance(TestCase):
    """Performance benchmarks for pool operations."""

    def setUp(self):
        self.pool = AccountPool()
        reset_pool_service()

        for i in range(10):
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

    def tearDown(self):
        reset_pool_service()

    def test_selection_performance(self):
        """Account selection is fast enough."""
        start = time.time()
        for _ in range(1000):
            self.pool.get_available_account()
        elapsed = time.time() - start

        # 1000 selections should complete in < 1 second
        self.assertLess(elapsed, 1.0, f"Too slow: {elapsed}s for 1000 selections")

        per_selection_ms = (elapsed / 1000) * 1000
        print(f"\nPerformance: {per_selection_ms:.3f}ms per selection")

    def test_status_performance(self):
        """Status retrieval is fast enough."""
        start = time.time()
        for _ in range(100):
            self.pool.get_pool_status()
        elapsed = time.time() - start

        # 100 status calls should complete in < 0.5 seconds
        self.assertLess(elapsed, 0.5, f"Too slow: {elapsed}s for 100 status calls")


if __name__ == "__main__":
    unittest.main()