"""Native smoke check for the same UI Automation path used by Alt+W.

The window is almost transparent and closes as soon as the worker finishes, so
running this script does not require manual interaction.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
import sys
import ctypes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learning_assistant  # bootstraps the Windows Qt runtime before PySide6
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from learning_assistant.services.selection import capture_selected_text


def main() -> int:
    app = QApplication.instance() or QApplication([])
    editor = QPlainTextEdit("Before selected phrase after")
    editor.setWindowTitle("LinguaSpark selection smoke")
    editor.resize(360, 80)
    editor.setWindowOpacity(0.05)
    editor.show()
    editor.raise_()
    editor.activateWindow()
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.setPosition(7)
    cursor.setPosition(22, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)

    result: dict[str, object] = {}

    def capture() -> None:
        result["value"] = capture_selected_text()

    def start_capture() -> None:
        hwnd = int(editor.winId())
        ctypes.windll.user32.ShowWindow(hwnd, 5)
        ctypes.windll.user32.BringWindowToTop(hwnd)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        editor.activateWindow()
        editor.setFocus()
        result["foreground"] = ctypes.windll.user32.GetForegroundWindow() == hwnd
        threading.Thread(target=capture, daemon=True).start()

    deadline = time.perf_counter() + 4

    def poll() -> None:
        if "value" in result or time.perf_counter() >= deadline:
            editor.close()
            app.quit()

    QTimer.singleShot(350, start_capture)
    QTimer.singleShot(5000, app.quit)
    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(25)
    app.exec()
    value = result.get("value", (None, ""))
    print(repr(value), f"foreground={result.get('foreground', False)}")
    return 0 if value and value[0] == "selected phrase" else 1


if __name__ == "__main__":
    raise SystemExit(main())
