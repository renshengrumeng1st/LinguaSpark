"""Composition root: this is the only place concrete providers are wired."""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QDate, QPoint, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from learning_assistant.controller import LearningController
from learning_assistant.core.paths import project_root
from learning_assistant.core.settings import SettingsStore
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.services.selection import GlobalHotkeyService, SelectionService
from learning_assistant.services.speech import SpeechService
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.main_window import MainWindow
from learning_assistant.ui.selection_popup import SelectionPopup
from learning_assistant.ui.theme import APP_QSS


logger = logging.getLogger(__name__)


class LearningAssistantApplication:
    def __init__(self, argv: list[str] | None = None):
        self.qt = QApplication(argv if argv is not None else sys.argv)
        self.qt.setApplicationName("LinguaSpark")
        self.qt.setOrganizationName("LinguaSpark")
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setStyleSheet(APP_QSS)

        self.settings = SettingsStore()
        self.dictionary = DictionaryRepository()
        self.dictionary.warmup()
        self.repository = LearningRepository()
        self.controller = LearningController(
            settings=self.settings,
            dictionary=self.dictionary,
            repository=self.repository,
        )
        self.speech = SpeechService(self.settings)
        self.main_window = MainWindow(self.controller, self.settings, self.speech)
        self.popup = SelectionPopup(self.controller)
        self.selection = SelectionService()
        self._review_message_active = False
        self.hotkeys = GlobalHotkeyService({
            "window": str(self.settings.get("window_hotkey", "alt+q")),
            "selection": str(self.settings.get("selection_hotkey", "alt+w")),
        })
        self._wire()
        self.tray = self._create_tray()
        self._refresh_review_action(self.repository.due_learning_count())
        self.review_timer = QTimer(self.qt)
        self.review_timer.setInterval(15 * 60 * 1000)
        self.review_timer.timeout.connect(self._check_review_reminder)
        QTimer.singleShot(2500, self._check_review_reminder)

    def _wire(self) -> None:
        self.hotkeys.triggered.connect(self._hotkey)
        self.selection.captured.connect(self._selection_captured)
        self.selection.failed.connect(self._selection_failed)
        self.popup.open_main_requested.connect(self._open_from_popup)
        self.popup.speak_requested.connect(self.main_window._speak)
        self.main_window.review_count_changed.connect(self._refresh_review_action)
        self.main_window.settings_opened.connect(self.hotkeys.stop)
        self.main_window.settings_closed.connect(self._reload_hotkeys)
        self.hotkeys.registration_failed.connect(self._hotkey_registration_failed)

    def _create_tray(self) -> QSystemTrayIcon:
        icon_path = project_root() / "assets" / "icon.ico"
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.qt.style().standardIcon(QStyle.SP_ComputerIcon)
        )
        tray = QSystemTrayIcon(icon, self.qt)
        window = self._hotkey_label("window_hotkey", "Alt+Q")
        selection = self._hotkey_label("selection_hotkey", "Alt+W")
        tray.setToolTip(f"LinguaSpark · {window} 呼出 · {selection} 划词")
        menu = QMenu()
        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self.main_window.show_front)
        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(self.main_window.open_settings)
        self.review_action = QAction("今日复习", menu)
        self.review_action.triggered.connect(self.main_window.open_review)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show_action)
        menu.addAction(self.review_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self.main_window.toggle_visibility()
            if reason == QSystemTrayIcon.Trigger else None
        )
        tray.messageClicked.connect(self._tray_message_clicked)
        tray.show()
        return tray

    def _refresh_review_action(self, count: int) -> None:
        self.review_action.setText(f"今日复习（{count}）")

    def _hotkey_label(self, key: str, default: str) -> str:
        value = str(self.settings.get(key, default))
        try:
            return GlobalHotkeyService.format_binding(value)
        except ValueError:
            return value

    def _tray_message_clicked(self) -> None:
        if self._review_message_active:
            self._review_message_active = False
            self.main_window.open_review()

    def _check_review_reminder(self) -> None:
        count = self.main_window.refresh_review_count()
        if not count or not bool(self.settings.get("review_reminders", True)):
            return
        today = QDate.currentDate().toString("yyyy-MM-dd")
        if self.settings.get("last_review_notice_date", "") == today:
            return
        self.tray.showMessage(
            "LinguaSpark · 今日复习",
            f"有 {count} 个单词等待复习，花几分钟巩固一下吧。",
            QSystemTrayIcon.Information,
            5000,
        )
        self._review_message_active = True
        self.settings.set("last_review_notice_date", today)
        self.settings.save()

    def _hotkey(self, name: str) -> None:
        if name == "window":
            self.main_window.toggle_visibility()
        elif name == "selection":
            self.selection.request()

    def _reload_hotkeys(self) -> None:
        self.hotkeys.stop()
        self.hotkeys = GlobalHotkeyService({
            "window": str(self.settings.get("window_hotkey", "alt+q")),
            "selection": str(self.settings.get("selection_hotkey", "alt+w")),
        })
        self.hotkeys.triggered.connect(self._hotkey)
        self.hotkeys.registration_failed.connect(self._hotkey_registration_failed)
        self.hotkeys.start()
        window = self._hotkey_label("window_hotkey", "Alt+Q")
        selection = self._hotkey_label("selection_hotkey", "Alt+W")
        self.tray.setToolTip(
            f"LinguaSpark · {window} 呼出 · {selection} 划词"
        )

    def _hotkey_registration_failed(self, name: str, binding: str) -> None:
        label = "显示窗口" if name == "window" else "划词翻译"
        message = f"{label}快捷键 {binding} 已被其他程序占用，请在设置中更换。"
        self.main_window.status.setText(message)
        self.tray.showMessage("快捷键注册失败", message, QSystemTrayIcon.Warning, 4500)

    def _selection_captured(self, text: str, context: str, x: int, y: int) -> None:
        self.popup.show_query(text, QPoint(x, y))
        self.main_window.input.setPlainText(text)
        self.main_window._last_auto_text = text
        self.controller.submit(text, context=context)

    def _selection_failed(self, message: str) -> None:
        self._review_message_active = False
        self.tray.showMessage("LinguaSpark", message, QSystemTrayIcon.Warning, 1800)

    def _open_from_popup(self, text: str) -> None:
        self.popup.hide()
        self.main_window.input.setPlainText(text)
        self.main_window.show_front()

    def run(self) -> int:
        self.hotkeys.start()
        self.review_timer.start()
        if not self.dictionary.available:
            logger.warning("Local dictionary database is missing")
        self.main_window.show_front()
        return self.qt.exec()

    def quit(self) -> None:
        self.hotkeys.stop()
        self.controller.cancel()
        self.speech.close()
        self.tray.hide()
        self.qt.quit()


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    application = LearningAssistantApplication()
    return application.run()
