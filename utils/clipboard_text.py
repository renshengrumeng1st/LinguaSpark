"""Clipboard text extraction — get selected text without image handling.

Two strategies:
1. Read from the clipboard directly (works when the user has already
   copied text, or when a hotkey-triggered copy was just performed).
2. Simulate Ctrl+C and then read the clipboard (for "selection translation").

This module is UI-independent so it can be unit-tested easily.
"""

import ctypes
from ctypes import wintypes
import logging
import time
from typing import Optional

logger = logging.getLogger("clipboard_text")

# ── Windows API constants ───────────────────────────────────

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Set proper return types for 64-bit
user32.OpenClipboard.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HGLOBAL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.CloseClipboard.restype = wintypes.BOOL

kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

VK_CONTROL = 0x11
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13


def _send_ctrl_c() -> None:
    """Send Ctrl+C via Windows keybd_event (bypasses keyboard hooks)."""
    # Press Ctrl
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    # Press C
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.03)
    # Release C
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    # Release Ctrl
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _read_clipboard_windows() -> Optional[str]:
    """Read clipboard text using Windows API (thread-safe, no tkinter needed)."""
    try:
        if not user32.OpenClipboard(None):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                text = ctypes.cast(ptr, ctypes.c_wchar_p).value
                return text if text and text.strip() else None
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.debug("Windows API clipboard read failed: %s", e)
        return None


def get_clipboard_text() -> Optional[str]:
    """Return the current text from the clipboard, or *None*."""
    text = _read_clipboard_windows()
    if text:
        return text
    # Fallback to tkinter for non-Windows
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            text = root.clipboard_get()
        except tk.TclError:
            text = None
        root.destroy()
        return text if text and text.strip() else None
    except Exception as e:
        logger.error("Failed to read clipboard: %s", e)
        return None


def get_selected_text_via_copy() -> Optional[str]:
    """Simulate Ctrl+C and read the copied text.

    1. WAIT for the user to physically release the Alt key (critical when
       triggered by a global hotkey — the user's finger is still on Alt)
    2. Simulate Ctrl+C via Windows keybd_event
    3. Wait for copy to complete
    4. Read clipboard
    """
    # Read current clipboard to detect changes
    before = get_clipboard_text()

    # Wait for the Alt key to be physically released.
    # When the global hotkey Alt+W fires, the user is still holding Alt.
    # If we send Ctrl+C while Alt is held, the target app receives
    # Alt+Ctrl+C (not a copy command) and nothing gets copied.
    try:
        import keyboard
        deadline = time.time() + 1.0  # max 1 second wait
        while time.time() < deadline:
            if not keyboard.is_pressed("alt"):
                break
            time.sleep(0.02)
    except ImportError:
        pass
    except Exception:
        pass

    # Small additional delay for OS to settle after key release
    time.sleep(0.05)

    # Simulate Ctrl+C using Windows API (bypasses keyboard hooks)
    try:
        _send_ctrl_c()
    except Exception as e:
        logger.error("Failed to send Ctrl+C: %s", e)
        return None

    # Wait for copy operation to complete
    time.sleep(0.2)

    after = get_clipboard_text()
    if after and after != before:
        return after
    if after:
        return after
    return None
