"""Global hotkey handler using native Windows RegisterHotKey with keyboard library fallback."""

import logging
import os
import threading
from typing import Callable, Optional

logger = logging.getLogger("hotkey")

# Virtual key code map for hotkey parsing
VK_MAP = {
    'enter': 0x0D, 'tab': 0x09, 'space': 0x20,
    'esc': 0x1B, 'escape': 0x1B,
    'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'printscreen': 0x2C, 'scrolllock': 0x91, 'pause': 0x13,
}

MOD_FLAGS = {
    'alt': 0x0001, 'menu': 0x0001,
    'ctrl': 0x0002, 'control': 0x0002,
    'shift': 0x0004,
    'win': 0x0008, 'windows': 0x0008,
}


def parse_hotkey_string(hotkey: str) -> tuple:
    """Parse a hotkey string like 'alt+q' or 'ctrl+shift+x' into (modifiers, vk_code)."""
    parts = hotkey.lower().split('+')
    mods = 0
    key = None

    for p in parts:
        p = p.strip()
        if p in MOD_FLAGS:
            mods |= MOD_FLAGS[p]
        else:
            key = p

    if not key:
        raise ValueError('No key specified in hotkey')

    if len(key) == 1:
        vk = ord(key.upper())
    elif key.startswith('f') and key[1:].isdigit():
        vk = 0x70 + (int(key[1:]) - 1)
    else:
        vk = VK_MAP.get(key, ord(key[0].upper()))

    return mods, vk


def validate_hotkey_string(hotkey: str) -> bool:
    """Check if a hotkey string is syntactically valid."""
    try:
        parse_hotkey_string(hotkey)
        return True
    except ValueError:
        return False


class HotkeyManager:
    """Manages global hotkey registration and handling."""

    def __init__(self):
        self._callback: Optional[Callable[[], None]] = None
        self._is_running = False
        self._hotkey = "alt+q"

        # keyboard lib fallback
        self._hotkey_handle = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

        # native Windows registration
        self._use_native = False
        self._native_thread: Optional[threading.Thread] = None
        self._native_thread_id: Optional[int] = None
        self._hotkey_id: int = 1

        # additional hotkeys (keyboard lib only)
        self._additional_hotkeys: dict[str, Callable] = {}
        self._additional_handles: list = []

    def register_hotkey(self, callback: Callable[[], None], hotkey: str = "alt+q") -> bool:
        self._callback = callback
        self._hotkey = hotkey

        # Try native Windows RegisterHotKey first (works across lock/unlock)
        if os.name == "nt":
            try:
                mods, vk = parse_hotkey_string(hotkey)
                self._use_native = True
                self._native_thread = threading.Thread(
                    target=self._native_message_loop, args=(mods, vk), daemon=True
                )
                self._native_thread.start()
                for _ in range(20):
                    if self._is_running:
                        logger.info("Global hotkey registered via native RegisterHotKey")
                        return True
                    threading.Event().wait(0.05)
            except Exception as e:
                logger.warning("Native RegisterHotKey failed: %s", e)
                self._use_native = False

        # Fallback to keyboard library
        try:
            import keyboard
            handle = keyboard.add_hotkey(hotkey, self._on_hotkey)
            self._hotkey_handle = handle
            self._is_running = True

            if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
                self._watchdog_stop.clear()
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog_loop, daemon=True
                )
                self._watchdog_thread.start()

            logger.info("Global hotkey registered via keyboard library (fallback)")
            return True
        except ImportError:
            logger.warning("keyboard library not available")
            return False
        except Exception as e:
            logger.warning("Could not register global hotkey: %s", e)
            return False

    def register_additional_hotkey(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Register an additional global hotkey alongside the primary one.
        
        Additional hotkeys use the keyboard library (not native RegisterHotKey)
        and share the same watchdog thread.
        """
        if not self._is_running:
            return False
        try:
            import keyboard
            handle = keyboard.add_hotkey(hotkey, callback)
            self._additional_handles.append(handle)
            self._additional_hotkeys[hotkey] = callback
            logger.info("Additional global hotkey %s registered", hotkey)
            return True
        except Exception as e:
            logger.warning("Could not register additional hotkey %s: %s", hotkey, e)
            return False
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error("Error in hotkey callback: %s", e)

    def _native_message_loop(self, modifiers: int, vk: int) -> None:
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return

        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            WM_HOTKEY = 0x0312

            self._native_thread_id = kernel32.GetCurrentThreadId()

            if not user32.RegisterHotKey(None, self._hotkey_id, modifiers, vk):
                self._is_running = False
                logger.warning("RegisterHotKey failed (check if hotkey is already registered)")
                return

            self._is_running = True
            msg = wintypes.MSG()
            while True:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res == 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    try:
                        if self._callback:
                            self._callback()
                    except Exception as e:
                        logger.error("Error in native hotkey callback: %s", e)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            user32.UnregisterHotKey(None, self._hotkey_id)
        except Exception as e:
            logger.error("Native message loop error: %s", e)
        finally:
            self._is_running = False

    def _watchdog_loop(self) -> None:
        try:
            import keyboard
        except Exception:
            return

        while not self._watchdog_stop.wait(10):
            try:
                if self._hotkey_handle is not None:
                    try:
                        keyboard.remove_hotkey(self._hotkey_handle)
                    except Exception as e:
                        logger.debug("watchdog: remove_hotkey failed: %s", e)
                handle = keyboard.add_hotkey(self._hotkey, self._on_hotkey)
                self._hotkey_handle = handle
                self._is_running = True
            except Exception as e:
                logger.debug("watchdog: re-register hotkey failed: %s", e)

    def unregister(self) -> None:
        if not self._is_running:
            return

        # Unregister additional hotkeys first
        try:
            import keyboard
            for handle in self._additional_handles:
                try:
                    keyboard.remove_hotkey(handle)
                except Exception:
                    pass
            self._additional_handles.clear()
            self._additional_hotkeys.clear()
        except Exception:
            pass

        if self._use_native and self._native_thread is not None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                WM_QUIT = 0x0012
                if self._native_thread_id:
                    user32.PostThreadMessageW(self._native_thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
            try:
                if self._native_thread and self._native_thread.is_alive():
                    self._native_thread.join(timeout=0.5)
            except Exception:
                pass
            self._use_native = False

        self._watchdog_stop.set()
        try:
            if self._watchdog_thread and self._watchdog_thread.is_alive():
                self._watchdog_thread.join(timeout=0.1)
        except Exception:
            pass

        try:
            import keyboard
            if self._hotkey_handle is not None:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass
            else:
                try:
                    keyboard.remove_hotkey(self._hotkey)
                except Exception:
                    pass
        except Exception:
            pass

        self._is_running = False

    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_hotkey(self) -> str:
        """Return the currently-configured hotkey string (public read access)."""
        return self._hotkey
