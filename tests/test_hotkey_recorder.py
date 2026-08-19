"""Tests for shortcut formatting — utils/shortcut_format.py"""

import unittest

from utils.shortcut_format import format_binding


class TestFormatBinding(unittest.TestCase):
    """Test the format_binding helper."""

    def test_ctrl_enter(self):
        self.assertEqual(
            format_binding("<Control-Return>"),
            "Ctrl+Enter",
        )

    def test_ctrl_shift_a(self):
        self.assertEqual(
            format_binding("<Control-Shift-A>"),
            "Ctrl+Shift+A",
        )

    def test_alt_f4(self):
        self.assertEqual(
            format_binding("<Alt-F4>"),
            "Alt+F4",
        )

    def test_single_key(self):
        self.assertEqual(
            format_binding("<F1>"),
            "F1",
        )


if __name__ == "__main__":
    unittest.main()
