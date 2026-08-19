"""Hotkey recorder widget — lets the user capture a keyboard binding.

Usage::

    recorder = HotkeyRecorder(parent, current="<Control-Return>")
    recorder.pack(fill="x")
    # later:
    binding = recorder.get_binding()  # e.g. "<Control-Shift-A>"

The widget shows the current binding as text.  When the user clicks it,
it enters "recording" mode and the next key combination pressed is
captured and displayed.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from utils.shortcut_format import format_binding


# Maps from tkinter keysym to canonical modifier names
_MODIFIER_SYMS = {
    "Control_L": "Control",
    "Control_R": "Control",
    "Alt_L": "Alt",
    "Alt_R": "Alt",
    "Shift_L": "Shift",
    "Shift_R": "Shift",
    "Meta_L": "Meta",
    "Meta_R": "Meta",
}

_MODIFIER_ORDER = ["Control", "Alt", "Shift", "Meta"]


class HotkeyRecorder(tk.Frame):
    """A button-like widget that records a hotkey combination."""

    def __init__(
        self,
        parent,
        current: str = "",
        width: int = 200,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)

        self._binding: str = current
        self._recording = False
        self._pressed_mods: set[str] = set()
        self._pressed_key: str = ""

        self._label = tk.Label(
            self,
            text=self._display_text(),
            font=("Microsoft YaHei UI", 11),
            bg="#3a3a3a" if not self._recording else "#0050a0",
            fg="white",
            width=4 if width < 100 else width // 8,
            padx=8, pady=4,
            cursor="hand2",
            borderwidth=1, relief="solid",
        )
        self._label.pack(fill="x", ipady=2)

        self._label.bind("<Button-1>", self._start_recording)
        self._label.bind("<FocusIn>", self._on_focus_in)
        self._label.bind("<FocusOut>", self._stop_recording)

        # Bind key events at the recorder level
        self._label.bind("<KeyPress>", self._on_key_press)
        self._label.bind("<KeyRelease>", self._on_key_release)

    # ── display helpers ──────────────────────────────────

    def _display_text(self) -> str:
        if self._recording:
            return "  请按下快捷键…  "
        if self._binding:
            return f"  {self._binding}  "
        return "  点击设置快捷键  "

    # ── recording ────────────────────────────────────────

    def _start_recording(self, event=None):
        self._recording = True
        self._pressed_mods.clear()
        self._pressed_key = ""
        self._label.configure(bg="#0050a0", text="  请按下快捷键…  ")
        self._label.focus_set()

    def _stop_recording(self, event=None):
        if not self._recording:
            return
        self._recording = False
        self._label.configure(bg="#3a3a3a")
        # If nothing was pressed, keep old binding
        self._label.configure(text=self._display_text())

    def _on_focus_in(self, event=None):
        pass

    def _on_key_press(self, event: tk.Event):
        if not self._recording:
            return

        keysym = event.keysym

        # Allow Escape to cancel recording
        if keysym == "Escape":
            self._stop_recording()
            return "break"

        mod_name = _MODIFIER_SYMS.get(keysym)
        if mod_name:
            self._pressed_mods.add(mod_name)
            self._update_recording_display()
            return "break"

        # It's a regular key
        self._pressed_key = self._canonical_key(event)
        self._finalize_recording()
        return "break"

    def _on_key_release(self, event: tk.Event):
        if not self._recording:
            return
        mod_name = _MODIFIER_SYMS.get(event.keysym)
        if mod_name:
            self._pressed_mods.discard(mod_name)

    def _canonical_key(self, event: tk.Event) -> str:
        """Return canonical key name from event."""
        keysym = event.keysym
        # Handle special keys
        special = {
            "Return": "Return",
            "Enter": "Return",
            "space": "space",
            "Tab": "Tab",
            "BackSpace": "BackSpace",
            "Delete": "Delete",
            "Escape": "Escape",
            "Up": "Up", "Down": "Down", "Left": "Right",
            "Home": "Home", "End": "End",
            "Page_Up": "PageUp", "Page_Down": "PageDown",
            "Insert": "Insert",
            "Print": "Print",
            "Menu": "Menu",
        }
        if keysym in special:
            return special[keysym]
        if keysym.startswith("F") and keysym[1:].isdigit():
            return keysym
        # Single character
        if len(keysym) == 1:
            return keysym.upper()
        return keysym

    def _update_recording_display(self):
        """Show currently held modifiers while recording."""
        parts = [p for p in _MODIFIER_ORDER if p in self._pressed_mods]
        if self._pressed_key:
            parts.append(self._pressed_key)
        display = "+".join(parts) if parts else "…"
        self._label.configure(text=f"  {display}  ")

    def _finalize_recording(self):
        """Build the binding string from pressed modifiers + key."""
        parts = [p for p in _MODIFIER_ORDER if p in self._pressed_mods]
        if self._pressed_key:
            parts.append(self._pressed_key)
        if parts:
            self._binding = "<" + "-".join(parts) + ">"
        self._recording = False
        self._pressed_mods.clear()
        self._pressed_key = ""
        self._label.configure(bg="#3a3a3a", text=self._display_text())

    # ── public API ───────────────────────────────────────

    def get_binding(self) -> str:
        """Return the captured tkinter binding string (e.g. '<Control-Return>')."""
        return self._binding

    def set_binding(self, binding: str) -> None:
        """Programmatically set the binding."""
        self._binding = binding
        self._label.configure(text=self._display_text())

    def clear(self) -> None:
        """Clear the binding."""
        self._binding = ""
        self._label.configure(text=self._display_text())
