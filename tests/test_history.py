"""Tests for utils/history.py"""

import os
import tempfile
import time
import unittest

from utils.history import HistoryManager, HistoryEntry


class TestHistoryEntry(unittest.TestCase):
    """Test HistoryEntry dataclass."""

    def test_round_trip(self):
        """to_dict / from_dict should preserve all fields."""
        entry = HistoryEntry(
            timestamp="2024-01-01 12:00:00",
            source_text="hello",
            result_text="你好",
            has_image=False,
            model="gpt-4",
        )
        d = entry.to_dict()
        restored = HistoryEntry.from_dict(d)
        self.assertEqual(restored.timestamp, entry.timestamp)
        self.assertEqual(restored.source_text, entry.source_text)
        self.assertEqual(restored.result_text, entry.result_text)
        self.assertEqual(restored.has_image, entry.has_image)
        self.assertEqual(restored.model, entry.model)


class TestHistoryManager(unittest.TestCase):
    """Test HistoryManager with temporary files."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        )
        self._tmp.close()
        self.hm = HistoryManager(history_file=self._tmp.name, max_entries=5)

    def tearDown(self):
        # Cancel any pending save timer
        if self.hm._save_timer:
            self.hm._save_timer.cancel()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _wait_for_save(self):
        """Wait for the debounced save to complete."""
        if self.hm._save_timer:
            self.hm._save_timer.join(timeout=3)

    def test_add_and_get(self):
        """Adding entries should make them retrievable."""
        self.hm.add(source_text="hello", result_text="你好", has_image=False)
        self._wait_for_save()
        entries = self.hm.get_all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source_text, "hello")

    def test_get_all_newest_first(self):
        """get_all should return entries newest first."""
        self.hm.add(source_text="first", result_text="第一", has_image=False)
        time.sleep(0.01)
        self.hm.add(source_text="second", result_text="第二", has_image=False)
        self._wait_for_save()
        entries = self.hm.get_all()
        self.assertEqual(entries[0].source_text, "second")
        self.assertEqual(entries[1].source_text, "first")

    def test_max_entries(self):
        """History should not exceed max_entries."""
        for i in range(10):
            self.hm.add(source_text=f"text{i}", result_text=f"结果{i}", has_image=False)
        self._wait_for_save()
        self.assertLessEqual(len(self.hm.get_all()), 5)

    def test_search(self):
        """Search should find entries by keyword."""
        self.hm.add(source_text="apple pie", result_text="苹果派", has_image=False)
        self.hm.add(source_text="banana", result_text="香蕉", has_image=False)
        self._wait_for_save()
        results = self.hm.search("apple")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_text, "apple pie")

    def test_search_case_insensitive(self):
        """Search should be case-insensitive."""
        self.hm.add(source_text="Hello World", result_text="你好世界", has_image=False)
        self._wait_for_save()
        self.assertEqual(len(self.hm.search("hello")), 1)
        self.assertEqual(len(self.hm.search("HELLO")), 1)
        self.assertEqual(len(self.hm.search("WORLD")), 1)

    def test_search_empty_keyword(self):
        """Empty keyword should return all entries."""
        self.hm.add(source_text="a", result_text="1", has_image=False)
        self.hm.add(source_text="b", result_text="2", has_image=False)
        self._wait_for_save()
        self.assertEqual(len(self.hm.search("")), 2)

    def test_clear(self):
        """clear should remove all entries."""
        self.hm.add(source_text="a", result_text="1", has_image=False)
        self._wait_for_save()
        self.assertTrue(self.hm.clear())
        self.assertEqual(len(self.hm.get_all()), 0)

    def test_save_and_reload(self):
        """Entries should persist across manager instances."""
        self.hm.add(source_text="persist", result_text="保存", has_image=True, model="gpt-4")
        self._wait_for_save()

        hm2 = HistoryManager(history_file=self._tmp.name, max_entries=5)
        entries = hm2.get_all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source_text, "persist")
        self.assertTrue(entries[0].has_image)
        if hm2._save_timer:
            hm2._save_timer.cancel()

    def test_text_truncation(self):
        """Long texts should be truncated to 500 chars."""
        long_text = "x" * 1000
        self.hm.add(source_text=long_text, result_text=long_text, has_image=False)
        self._wait_for_save()
        entries = self.hm.get_all()
        self.assertEqual(len(entries[0].source_text), 500)
        self.assertEqual(len(entries[0].result_text), 500)


if __name__ == "__main__":
    unittest.main()
