import pytest

from learning_assistant.services.selection import GlobalHotkeyService, INPUT
import ctypes


def test_hotkey_parser():
    assert GlobalHotkeyService._parse("<Alt-W>") == (0x0001, ord("W"))
    assert GlobalHotkeyService._parse("ctrl+shift+f2") == (0x0002 | 0x0004, 0x71)
    assert GlobalHotkeyService.format_binding("<control-shift-f2>") == "Ctrl+Shift+F2"


def test_hotkey_parser_rejects_unsupported_key():
    with pytest.raises(ValueError):
        GlobalHotkeyService._parse("alt+space")
    with pytest.raises(ValueError):
        GlobalHotkeyService._parse("alt+q+w")
    with pytest.raises(ValueError):
        GlobalHotkeyService._parse("F25")


def test_windows_input_structure_has_native_size():
    # SendInput rejects a keyboard-only union (32 bytes) on 64-bit Windows.
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
