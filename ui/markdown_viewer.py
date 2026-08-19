"""Markdown result viewer for the translation assistant.

A thin wrapper around tkinter.Text that renders a useful subset of Markdown:
headings, bold, italic, inline code, fenced code blocks, bullet/numbered lists,
and block-quotes.  The widget is read-only and auto-scrolls.

Designed as a drop-in replacement for the previous CTkTextbox used to display
translation results.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional


# ---------------------------------------------------------------------------
# Markdown → tkinter tag rendering
# ---------------------------------------------------------------------------

# Header levels → (font_size, spacing after)
_HEADER_STYLE: dict[int, tuple[int, int]] = {
    1: (22, 10),
    2: (18, 8),
    3: (16, 6),
    4: (14, 4),
}


def _render_markdown(text_widget: tk.Text, text: str) -> None:
    """Parse *text* as markdown and insert it into *text_widget*."""
    import re

    text_widget.delete("1.0", "end")

    lines = text.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # ── fenced code block ──────────────────────────────────────
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_text = "\n".join(code_lines)
            text_widget.insert("end", code_text + "\n", "code_block")
            continue

        # ── blank line ─────────────────────────────────────────────
        if not line.strip():
            text_widget.insert("end", "\n")
            i += 1
            continue

        # ── headers ────────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            content = m.group(2)
            font_size = _HEADER_STYLE.get(level, (12, 2))[0]
            spacing = _HEADER_STYLE.get(level, (12, 2))[1]
            tag = f"h{level}_{font_size}"
            if tag not in text_widget.tag_names():
                text_widget.tag_config(tag, font=("Microsoft YaHei UI", font_size, "bold"))
            text_widget.insert("end", content + "\n", tag)
            if spacing:
                text_widget.tag_config(tag, spacing1=spacing // 2, spacing3=spacing // 2)
            i += 1
            continue

        # ── block-quote ────────────────────────────────────────────
        if line.strip().startswith(">"):
            content = line.strip().lstrip(">").strip()
            text_widget.insert("end", content + "\n", "blockquote")
            i += 1
            continue

        # ── bullet list ────────────────────────────────────────────
        if re.match(r"^\s*[-*+]\s+", line):
            content = re.sub(r"^\s*[-*+]\s+", "", line)
            text_widget.insert("end", "• ", "bullet")
            _insert_inline(text_widget, content)
            text_widget.insert("end", "\n")
            i += 1
            continue

        # ── numbered list ──────────────────────────────────────────
        m = re.match(r"^\s*(\d+)[.)]\s+(.*)", line)
        if m:
            content = m.group(2)
            text_widget.insert("end", f"{m.group(1)}. ", "number")
            _insert_inline(text_widget, content)
            text_widget.insert("end", "\n")
            i += 1
            continue

        # ── normal paragraph ───────────────────────────────────────
        _insert_inline(text_widget, line)
        text_widget.insert("end", "\n")
        i += 1


def _insert_inline(text_widget: tk.Text, text: str) -> None:
    """Insert *text* into the widget, recognising inline markdown spans.

    Processing order matters: code spans are handled first (their content
    is never further processed), then bold, then italic.  Each pass
    works on the remaining plain-text segments of the previous pass,
    preventing greedy-match conflicts.
    """
    import re

    # Pass 1: code spans (highest priority — content is literal)
    segments: list[tuple[str, str | None]] = [(text, None)]
    for marker in ("`",):
        new_segments: list[tuple[str, str | None]] = []
        pat = re.compile(r"`([^`]+)`")
        for seg_text, seg_tag in segments:
            if seg_tag is not None:
                # Already tagged — keep as-is
                new_segments.append((seg_text, seg_tag))
                continue
            pos = 0
            for m in pat.finditer(seg_text):
                if m.start() > pos:
                    new_segments.append((seg_text[pos:m.start()], None))
                new_segments.append((m.group(1), "inline_code"))
                pos = m.end()
            if pos < len(seg_text):
                new_segments.append((seg_text[pos:], None))
        segments = new_segments

    # Pass 2: bold (**...**)
    new_segments = []
    pat = re.compile(r"\*\*(.+?)\*\*")
    for seg_text, seg_tag in segments:
        if seg_tag is not None:
            new_segments.append((seg_text, seg_tag))
            continue
        pos = 0
        for m in pat.finditer(seg_text):
            if m.start() > pos:
                new_segments.append((seg_text[pos:m.start()], None))
            new_segments.append((m.group(1), "bold"))
            pos = m.end()
        if pos < len(seg_text):
            new_segments.append((seg_text[pos:], None))
    segments = new_segments

    # Pass 3: italic (*...* or _..._)
    new_segments = []
    pat = re.compile(r"\*([^*]+)\*|_([^_]+)_")
    for seg_text, seg_tag in segments:
        if seg_tag is not None:
            new_segments.append((seg_text, seg_tag))
            continue
        pos = 0
        for m in pat.finditer(seg_text):
            if m.start() > pos:
                new_segments.append((seg_text[pos:m.start()], None))
            # group(1) for *, group(2) for _
            new_segments.append((m.group(1) or m.group(2), "italic"))
            pos = m.end()
        if pos < len(seg_text):
            new_segments.append((seg_text[pos:], None))
    segments = new_segments

    # Insert all segments
    for seg_text, seg_tag in segments:
        if seg_tag:
            text_widget.insert("end", seg_text, seg_tag)
        else:
            text_widget.insert("end", seg_text)


# ---------------------------------------------------------------------------
# MarkdownViewer widget
# ---------------------------------------------------------------------------

class MarkdownViewer(tk.Frame):
    """Read-only markdown-rendering text widget inside a scrollbar."""

    # Layout constants — extracted for easy theming / DPI scaling
    PAD_X = 12
    PAD_Y = 10
    LINE_SPACING = 3
    PARA_SPACING = 3

    def __init__(self, parent, font: tuple = ("Microsoft YaHei UI", 12), **kwargs):
        super().__init__(parent, **kwargs)

        # Scrollbar
        self._scrollbar = tk.Scrollbar(self)
        self._scrollbar.pack(side="right", fill="y")

        # Text widget
        self._text = tk.Text(
            self,
            wrap="word",
            font=font,
            borderwidth=0,
            highlightthickness=0,
            padx=self.PAD_X,
            pady=self.PAD_Y,
            spacing2=self.LINE_SPACING,
            spacing3=self.PARA_SPACING,
            yscrollcommand=self._scrollbar.set,
            state="disabled",
            cursor="arrow",
        )
        self._text.pack(fill="both", expand=True)
        self._scrollbar.config(command=self._text.yview)

        # Tag styles
        self._text.tag_config("bold", font=(font[0], font[1], "bold"))
        self._text.tag_config("italic", font=(font[0], font[1], "italic"))
        self._text.tag_config(
            "inline_code",
            font=("Consolas", 13),
            background="#e0e0e0",
            foreground="#d63384",
        )
        self._text.tag_config(
            "code_block",
            font=("Consolas", 13),
            background="#f5f5f5",
            foreground="#333333",
            lmargin1=12,
            lmargin2=12,
            rmargin=12,
        )
        self._text.tag_config(
            "blockquote",
            foreground="#6a737d",
            lmargin1=16,
            lmargin2=16,
            font=(font[0], font[1], "italic"),
        )
        self._text.tag_config("bullet", foreground="#3b82f6", font=(font[0], font[1], "bold"))
        self._text.tag_config("number", foreground="#3b82f6", font=(font[0], font[1], "bold"))

        # Raw buffer for streaming content
        self._raw = ""

    # ── public API ──────────────────────────────────────────────

    def set_content(self, markdown_text: str) -> None:
        """Replace full content with *markdown_text* (rendered)."""
        self._raw = markdown_text
        self._text.configure(state="normal")
        _render_markdown(self._text, markdown_text)
        self._text.configure(state="disabled")

    def append_raw(self, chunk: str) -> None:
        """Append raw streaming text (no rendering, just accumulate)."""
        self._raw += chunk
        self._text.configure(state="normal")
        self._text.insert("end", chunk)
        self._text.see("end")
        self._text.configure(state="disabled")

    def clear(self) -> None:
        """Clear all content."""
        self._raw = ""
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")

    def rerender(self) -> None:
        """Re-render the accumulated raw text as markdown (call after stream ends)."""
        self._text.configure(state="normal")
        _render_markdown(self._text, self._raw)
        self._text.see("end")
        self._text.configure(state="disabled")

    def get_raw(self) -> str:
        """Return the accumulated raw markdown text."""
        return self._raw

    def see(self, index: str) -> None:
        self._text.see(index)
