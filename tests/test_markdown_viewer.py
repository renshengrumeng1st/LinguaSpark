"""Tests for ui/markdown_viewer.py — _render_markdown and _insert_inline logic."""

import tkinter as tk
import unittest

from ui.markdown_viewer import _render_markdown, _insert_inline


def _render_to_text(widget: tk.Text) -> str:
    """Get the plain text from a tk.Text widget (ignoring tags)."""
    return widget.get("1.0", "end")


# Use a single shared root for all tests in this module
_root: tk.Tk | None = None


def _get_root() -> tk.Tk:
    global _root
    if _root is None or not _root.winfo_exists():
        _root = tk.Tk()
        _root.withdraw()
    return _root


class TestRenderMarkdown(unittest.TestCase):
    """Test _render_markdown function."""

    def setUp(self):
        self.root = _get_root()
        frame = tk.Frame(self.root)
        frame.pack()
        self.widget = tk.Text(frame)
        self.widget.pack()

    def test_plain_text(self):
        _render_markdown(self.widget, "hello world")
        self.assertIn("hello world", _render_to_text(self.widget))

    def test_bold(self):
        _render_markdown(self.widget, "**bold text**")
        self.assertIn("bold text", _render_to_text(self.widget))

    def test_italic(self):
        _render_markdown(self.widget, "*italic text*")
        self.assertIn("italic text", _render_to_text(self.widget))

    def test_header(self):
        _render_markdown(self.widget, "# My Title")
        self.assertIn("My Title", _render_to_text(self.widget))

    def test_code_block(self):
        _render_markdown(self.widget, "```\ncode line\n```")
        self.assertIn("code line", _render_to_text(self.widget))

    def test_bullet_list(self):
        _render_markdown(self.widget, "- item one\n- item two")
        text = _render_to_text(self.widget)
        self.assertIn("item one", text)
        self.assertIn("item two", text)

    def test_numbered_list(self):
        _render_markdown(self.widget, "1. first\n2. second")
        text = _render_to_text(self.widget)
        self.assertIn("first", text)
        self.assertIn("second", text)

    def test_blockquote(self):
        _render_markdown(self.widget, "> quoted text")
        self.assertIn("quoted text", _render_to_text(self.widget))

    def test_empty_string(self):
        _render_markdown(self.widget, "")
        text = _render_to_text(self.widget)
        # Should not crash, may have trailing newline
        self.assertTrue(len(text) <= 2)

    def test_multiple_blocks(self):
        _render_markdown(self.widget, "# Title\n\nSome **bold** text.\n\n- item")
        text = _render_to_text(self.widget)
        self.assertIn("Title", text)
        self.assertIn("bold", text)
        self.assertIn("item", text)


class TestInsertInline(unittest.TestCase):
    """Test _insert_inline function."""

    def setUp(self):
        self.root = _get_root()
        frame = tk.Frame(self.root)
        frame.pack()
        self.widget = tk.Text(frame)
        self.widget.pack()

    def test_inline_code(self):
        _insert_inline(self.widget, "use `print()` function")
        self.assertIn("print()", _render_to_text(self.widget))

    def test_nested_bold_in_italic_context(self):
        """Bold markers should be correctly identified."""
        _insert_inline(self.widget, "**bold** and more")
        self.assertIn("bold", _render_to_text(self.widget))
        self.assertIn("and more", _render_to_text(self.widget))

    def test_underscore_italic(self):
        _insert_inline(self.widget, "_italic_ text")
        self.assertIn("italic", _render_to_text(self.widget))

    def test_mixed_formats(self):
        _insert_inline(self.widget, "**bold** and *italic* and `code`")
        text = _render_to_text(self.widget)
        self.assertIn("bold", text)
        self.assertIn("italic", text)
        self.assertIn("code", text)


if __name__ == "__main__":
    unittest.main()
