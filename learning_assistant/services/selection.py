"""Global hotkeys and fast selected-text capture on Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import threading
import time
import uuid

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCursor


logger = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
MOD_NOREPEAT = 0x4000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def _configure_win32() -> tuple[object, object]:
    """Declare pointer-sized Win32 signatures explicitly for 64-bit Python."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _send_ctrl_c() -> None:
    user32, _ = _configure_win32()
    inputs = (INPUT * 4)(
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(VK_C, 0, 0, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(VK_C, 0, KEYEVENTF_KEYUP, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0))),
    )
    sent = user32.SendInput(4, inputs, ctypes.sizeof(INPUT))
    if sent != 4:
        raise ctypes.WinError()


def _read_clipboard_text(retries: int = 8) -> str | None:
    user32, kernel32 = _configure_win32()
    for _ in range(retries):
        if user32.OpenClipboard(None):
            try:
                if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    return None
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                pointer = kernel32.GlobalLock(handle) if handle else None
                if not pointer:
                    return None
                try:
                    value = ctypes.wstring_at(pointer)
                    return value.strip() or None
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        time.sleep(0.008)
    return None


def _write_clipboard_text(text: str) -> bool:
    user32, kernel32 = _configure_win32()
    raw = (text + "\0").encode("utf-16-le")
    for _ in range(8):
        if user32.OpenClipboard(None):
            handle = None
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return False
                ctypes.memmove(pointer, raw, len(raw))
                kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    return False
                handle = None  # the system owns it now
                return True
            finally:
                user32.CloseClipboard()
                if handle:
                    kernel32.GlobalFree(handle)
        time.sleep(0.008)
    return False


def _clear_clipboard() -> None:
    user32, _ = _configure_win32()
    for _ in range(8):
        if user32.OpenClipboard(None):
            try:
                user32.EmptyClipboard()
            finally:
                user32.CloseClipboard()
            return
        time.sleep(0.008)


class _OleClipboardSnapshot:
    """Keep the complete clipboard IDataObject alive while Ctrl+C is sent."""

    def __init__(self) -> None:
        self.ole32 = ctypes.windll.ole32
        self.pointer = ctypes.c_void_p()
        self.initialized = self.ole32.OleInitialize(None) in (0, 1)
        self.ole32.OleGetClipboard.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.ole32.OleGetClipboard.restype = ctypes.c_long
        self.ole32.OleSetClipboard.argtypes = [ctypes.c_void_p]
        self.ole32.OleSetClipboard.restype = ctypes.c_long
        if self.ole32.OleGetClipboard(ctypes.byref(self.pointer)) < 0:
            self.pointer = ctypes.c_void_p()

    def restore(self, fallback_text: str | None) -> None:
        try:
            if self.pointer:
                self.ole32.OleSetClipboard(self.pointer)
            elif fallback_text is not None:
                _write_clipboard_text(fallback_text)
            else:
                _clear_clipboard()
        finally:
            if self.pointer:
                vtable = ctypes.cast(
                    self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
                release(self.pointer)
                self.pointer = ctypes.c_void_p()
            if self.initialized:
                self.ole32.OleUninitialize()


def selected_text_via_uia() -> tuple[str | None, str]:
    """Try UI Automation first so the user's clipboard is untouched."""
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        automation = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        focused = automation.GetFocusedElement()
        if not focused:
            return None, ""
        pattern_unknown = focused.GetCurrentPattern(UIA.UIA_TextPatternId)
        if not pattern_unknown:
            return None, ""
        pattern = pattern_unknown.QueryInterface(UIA.IUIAutomationTextPattern)
        ranges = pattern.GetSelection()
        pieces: list[str] = []
        context = ""
        for index in range(ranges.Length):
            selected_range = ranges.GetElement(index)
            value = str(selected_range.GetText(-1)).strip()
            if value:
                pieces.append(value)
            if index == 0:
                try:
                    surrounding = selected_range.Clone()
                    surrounding.ExpandToEnclosingUnit(UIA.TextUnit_Line)
                    context = str(surrounding.GetText(500)).strip()
                except Exception:
                    context = ""
        text = "\n".join(pieces).strip()
        if context == text:
            context = ""
        return (text or None), context
    except Exception as exc:
        logger.debug("UI Automation selection unavailable: %s", exc)
        return None, ""
    finally:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass


def selected_text_via_clipboard(timeout: float = 0.35) -> str | None:
    """Copy selection without confusing old clipboard text for a selection."""
    if os.name != "nt":
        return None
    user32, _ = _configure_win32()
    snapshot = _OleClipboardSnapshot()
    before_text = _read_clipboard_text()
    sentinel = f"__LINGUASPARK_SELECTION_{uuid.uuid4().hex}__"
    try:
        if not _write_clipboard_text(sentinel):
            return None
        before_sequence = user32.GetClipboardSequenceNumber()
        release_deadline = time.perf_counter() + 0.3
        while (
            time.perf_counter() < release_deadline
            and user32.GetAsyncKeyState(VK_MENU) & 0x8000
        ):
            time.sleep(0.005)
        _send_ctrl_c()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if user32.GetClipboardSequenceNumber() != before_sequence:
                selected = _read_clipboard_text()
                return selected if selected and selected != sentinel else None
            time.sleep(0.008)
        return None
    finally:
        snapshot.restore(before_text)


def capture_selected_text() -> tuple[str | None, str]:
    text, context = selected_text_via_uia()
    if text:
        return text, context
    return selected_text_via_clipboard(), ""


class SelectionService(QObject):
    captured = Signal(str, str, int, int)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._generation = 0
        self._active = False
        self._pending: tuple[int, int, int] | None = None

    def request(self) -> None:
        anchor = QCursor.pos()
        with self._lock:
            self._generation += 1
            self._pending = (self._generation, anchor.x(), anchor.y())
            if self._active:
                return
            self._active = True

        def worker() -> None:
            while True:
                with self._lock:
                    pending = self._pending
                    self._pending = None
                if pending is None:
                    with self._lock:
                        self._active = False
                    return
                generation, x, y = pending
                self._capture_once(generation, x, y)

        threading.Thread(target=worker, name="selection-capture", daemon=True).start()

    def _capture_once(self, generation: int, x: int, y: int) -> None:
        try:
            text, context = capture_selected_text()
            with self._lock:
                current = generation == self._generation
            if not current:
                return
            if text:
                self.captured.emit(text, context, x, y)
            else:
                self.failed.emit("未读取到选中文字")
        except Exception as exc:
            logger.exception("Selection capture failed")
            with self._lock:
                current = generation == self._generation
            if current:
                self.failed.emit(f"读取选区失败：{exc}")


class GlobalHotkeyService(QObject):
    """One native message loop owns all global hotkeys."""

    triggered = Signal(str)
    registration_failed = Signal(str, str)

    MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}

    def __init__(self, bindings: dict[str, str], parent: QObject | None = None):
        super().__init__(parent)
        self.bindings = bindings
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._stop = threading.Event()

    @classmethod
    def _parse(cls, binding: str) -> tuple[int, int]:
        cleaned = binding.strip().strip("<>").replace("-", "+").casefold()
        parts = [item.strip() for item in cleaned.split("+") if item.strip()]
        modifiers = 0
        keys: list[str] = []
        for part in parts:
            normalized = "ctrl" if part == "control" else part
            if normalized in cls.MODIFIERS:
                modifiers |= cls.MODIFIERS[normalized]
            else:
                keys.append(part)
        if len(keys) != 1:
            raise ValueError(f"unsupported hotkey: {binding}")
        key = keys[0]
        if len(key) == 1 and key.isalnum():
            virtual_key = ord(key.upper())
        elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
            virtual_key = 0x70 + int(key[1:]) - 1
        else:
            raise ValueError(f"unsupported hotkey: {binding}")
        return modifiers, virtual_key

    @classmethod
    def format_binding(cls, binding: str) -> str:
        modifiers, virtual_key = cls._parse(binding)
        parts = [
            label
            for name, label in (("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("win", "Win"))
            if modifiers & cls.MODIFIERS[name]
        ]
        if 0x70 <= virtual_key <= 0x87:
            parts.append(f"F{virtual_key - 0x70 + 1}")
        else:
            parts.append(chr(virtual_key))
        return "+".join(parts)

    def start(self) -> None:
        if os.name != "nt" or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        id_to_name: dict[int, str] = {}
        try:
            for offset, (name, binding) in enumerate(self.bindings.items(), start=1):
                try:
                    modifiers, key = self._parse(binding)
                except ValueError:
                    self.registration_failed.emit(name, binding)
                    continue
                identifier = 0x4C00 + offset
                if user32.RegisterHotKey(None, identifier, modifiers | MOD_NOREPEAT, key):
                    id_to_name[identifier] = name
                else:
                    logger.warning("Could not register hotkey %s", binding)
                    self.registration_failed.emit(name, binding)
            message = wintypes.MSG()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == 0x0312 and message.wParam in id_to_name:
                    self.triggered.emit(id_to_name[message.wParam])
        finally:
            for identifier in id_to_name:
                user32.UnregisterHotKey(None, identifier)

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread_id = None
