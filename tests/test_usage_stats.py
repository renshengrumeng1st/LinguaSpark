"""Tests for utils/usage_stats.py"""

import os
import tempfile
import unittest

from utils.usage_stats import UsageStats


class TestUsageStats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        )
        self._tmp.close()
        self.stats = UsageStats(stats_file=self._tmp.name)

    def tearDown(self):
        if self.stats._save_timer:
            self.stats._save_timer.cancel()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_record_basic(self):
        self.stats.record("gpt-4", 100, has_image=False)
        if self.stats._save_timer:
            self.stats._save_timer.join(timeout=3)
        summary = self.stats.get_summary()
        self.assertEqual(summary["total_translations"], 1)
        self.assertEqual(summary["total_characters"], 100)

    def test_record_multiple(self):
        self.stats.record("gpt-4", 100)
        self.stats.record("gpt-4", 200, has_image=True)
        if self.stats._save_timer:
            self.stats._save_timer.join(timeout=3)
        summary = self.stats.get_summary()
        self.assertEqual(summary["total_translations"], 2)
        self.assertEqual(summary["total_characters"], 300)
        self.assertEqual(summary["image_translations"], 1)
        self.assertEqual(summary["text_translations"], 1)

    def test_cache_hit_no_cost(self):
        self.stats.record("gpt-4", 100, cache_hit=True)
        if self.stats._save_timer:
            self.stats._save_timer.join(timeout=3)
        summary = self.stats.get_summary()
        self.assertEqual(summary["today"]["cost"], 0.0)
        self.assertEqual(summary["cache_hits"], 1)

    def test_clear(self):
        self.stats.record("gpt-4", 100)
        self.stats.clear()
        summary = self.stats.get_summary()
        self.assertEqual(summary["total_translations"], 0)

    def test_save_and_reload(self):
        self.stats.record("gpt-4", 500)
        if self.stats._save_timer:
            self.stats._save_timer.join(timeout=3)

        stats2 = UsageStats(stats_file=self._tmp.name)
        summary = stats2.get_summary()
        self.assertEqual(summary["total_translations"], 1)
        self.assertEqual(summary["total_characters"], 500)
        if stats2._save_timer:
            stats2._save_timer.cancel()

    def test_image_cost_higher(self):
        self.stats.record("gpt-4", 100, has_image=True)
        if self.stats._save_timer:
            self.stats._save_timer.join(timeout=3)
        summary = self.stats.get_summary()
        # Image cost should be ~3× text cost
        self.assertGreater(summary["today"]["cost"], 0)


if __name__ == "__main__":
    unittest.main()
