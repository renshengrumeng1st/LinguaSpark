"""Tests for utils/translation_cache.py"""

import os
import tempfile
import unittest

from utils.translation_cache import TranslationCache


class TestTranslationCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        )
        self._tmp.close()
        self.cache = TranslationCache(cache_file=self._tmp.name, max_entries=100)

    def tearDown(self):
        if self.cache._save_timer:
            self.cache._save_timer.cancel()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_cache_miss(self):
        self.assertIsNone(self.cache.get("hello", "gpt-4"))

    def test_put_and_get(self):
        self.cache.put("hello", "gpt-4", "你好")
        # Wait for debounced save
        if self.cache._save_timer:
            self.cache._save_timer.join(timeout=3)
        result = self.cache.get("hello", "gpt-4")
        self.assertEqual(result, "你好")

    def test_model_change_invalidates(self):
        self.cache.put("hello", "gpt-4", "你好")
        if self.cache._save_timer:
            self.cache._save_timer.join(timeout=3)
        # Different model → miss
        self.assertIsNone(self.cache.get("hello", "gpt-3.5"))

    def test_clear(self):
        self.cache.put("hello", "gpt-4", "你好")
        self.cache.clear()
        self.assertIsNone(self.cache.get("hello", "gpt-4"))
        self.assertEqual(self.cache.size, 0)

    def test_save_and_reload(self):
        self.cache.put("hello", "gpt-4", "你好")
        if self.cache._save_timer:
            self.cache._save_timer.join(timeout=3)

        # Reload
        cache2 = TranslationCache(cache_file=self._tmp.name)
        self.assertEqual(cache2.get("hello", "gpt-4"), "你好")
        if cache2._save_timer:
            cache2._save_timer.cancel()

    def test_result_truncation(self):
        long_result = "x" * 2000
        self.cache.put("hello", "gpt-4", long_result)
        if self.cache._save_timer:
            self.cache._save_timer.join(timeout=3)
        result = self.cache.get("hello", "gpt-4")
        self.assertTrue(len(result) <= 1000)

    def test_size_property(self):
        self.assertEqual(self.cache.size, 0)
        self.cache.put("a", "m", "1")
        self.assertEqual(self.cache.size, 1)

    def test_whitespace_normalization_cache_hit(self):
        """Text differing only in whitespace should produce a cache hit."""
        self.cache.put("hello world", "gpt-4", "你好世界")
        if self.cache._save_timer:
            self.cache._save_timer.join(timeout=3)
        # Different whitespace — should still hit
        self.assertEqual(self.cache.get("  hello   world  ", "gpt-4"), "你好世界")
        self.assertEqual(self.cache.get("hello\nworld", "gpt-4"), "你好世界")


if __name__ == "__main__":
    unittest.main()
