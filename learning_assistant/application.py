"""Composition root: this is the only place concrete providers are wired."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from PySide6.QtCore import QDate, QPoint, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from learning_assistant.controller import LearningController
from learning_assistant.core.paths import project_root
from learning_assistant.core.settings import SettingsStore
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.services.pdf_translation import QtPdfTranslationClient
from learning_assistant.services.selection import GlobalHotkeyService, SelectionService
from learning_assistant.services.speech import SpeechService
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.main_window import MainWindow
from learning_assistant.ui.mode_chooser import ModeChooser
from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
from learning_assistant.ui.selection_popup import SelectionPopup
from learning_assistant.ui.theme import APP_QSS


logger = logging.getLogger(__name__)


class ApplicationModeRouter:
    """Lazily creates mode windows and keeps only one mode visible."""

    def __init__(
        self,
        compact_factory: Callable[[], MainWindow],
        pdf_factory: Callable[[], PdfReaderWindow],
    ):
        self._compact_factory = compact_factory
        self._pdf_factory = pdf_factory
        self.chooser = ModeChooser()
        self.compact_window: MainWindow | None = None
        self.pdf_window: PdfReaderWindow | None = None
        self.chooser.compact_requested.connect(self.show_compact)
        self.chooser.pdf_requested.connect(self.show_pdf)

    def show_chooser(self) -> None:
        if self.compact_window:
            self.compact_window.hide()
        if self.pdf_window:
            self.pdf_window.hide()
        self.chooser.show_front()

    def show_compact(self) -> MainWindow:
        if self.compact_window is None:
            self.compact_window = self._compact_factory()
        if self.pdf_window:
            self.pdf_window.hide()
        self.chooser.hide()
        self.compact_window.show_front()
        return self.compact_window

    def toggle_compact(self) -> MainWindow:
        if self.compact_window is not None and self.compact_window.isVisible():
            self.compact_window.hide()
            return self.compact_window
        return self.show_compact()

    def show_pdf(self) -> PdfReaderWindow:
        if self.pdf_window is None:
            self.pdf_window = self._pdf_factory()
        if self.compact_window:
            self.compact_window.hide()
        self.chooser.hide()
        self.pdf_window.show_front()
        return self.pdf_window


class LearningAssistantApplication:
    def __init__(self, argv: list[str] | None = None):
        self.qt = QApplication(argv if argv is not None else sys.argv)
        self.qt.setApplicationName("LinguaSpark")
        self.qt.setOrganizationName("LinguaSpark")
        self.qt.setQuitOnLastWindowClosed(False)
        self.app_icon = self._install_application_icon()
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
        self.main_window: MainWindow | None = None
        self.pdf_client: QtPdfTranslationClient | None = None
        self.popup = SelectionPopup(self.controller)
        self.selection = SelectionService()
        self._review_message_active = False
        self.hotkeys = GlobalHotkeyService({
            "window": str(self.settings.get("window_hotkey", "alt+q")),
            "selection": str(self.settings.get("selection_hotkey", "alt+w")),
        })
        self.mode_router = ApplicationModeRouter(
            self._create_compact_window,
            self._create_pdf_window,
        )
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
        self.popup.speak_requested.connect(self._speak_from_popup)
        self.hotkeys.registration_failed.connect(self._hotkey_registration_failed)

    def _create_compact_window(self) -> MainWindow:
        window = MainWindow(self.controller, self.settings, self.speech)
        self.main_window = window
        window.review_count_changed.connect(self._refresh_review_action)
        window.settings_opened.connect(self.hotkeys.stop)
        window.settings_closed.connect(self._reload_hotkeys)
        return window

    def _create_pdf_window(self) -> PdfReaderWindow:
        window = PdfReaderWindow(self.settings, self._create_pdf_controller)
        window.compact_mode_requested.connect(self.mode_router.show_compact)
        window.settings_requested.connect(self._open_settings)
        return window

    def _create_pdf_controller(self) -> PdfTranslationController:
        if self.pdf_client is None:
            self.pdf_client = QtPdfTranslationClient(self.qt)
        return PdfTranslationController(
            self.settings,
            self.repository,
            self.pdf_client,
        )

    def _ensure_compact_window(self) -> MainWindow:
        if self.mode_router.compact_window is None:
            self.mode_router.compact_window = self._create_compact_window()
        return self.mode_router.compact_window

    def _speak_from_popup(self, text: str) -> None:
        locale = str(self.settings.get("tts", {}).get("voice_locale", "en-US"))
        self.speech.speak(text, locale)

    def _open_settings(self) -> None:
        self._ensure_compact_window().open_settings()

    def _install_application_icon(self) -> QIcon:
        icon_path = project_root() / "assets" / "icon.ico"
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.qt.style().standardIcon(QStyle.SP_ComputerIcon)
        )
        self.qt.setWindowIcon(icon)
        return icon

    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self.app_icon, self.qt)
        window = self._hotkey_label("window_hotkey", "Alt+Q")
        selection = self._hotkey_label("selection_hotkey", "Alt+W")
        tray.setToolTip(f"LinguaSpark · {window} 呼出 · {selection} 划词")
        menu = QMenu()
        show_action = QAction("选择模式", menu)
        show_action.triggered.connect(self.mode_router.show_chooser)
        compact_action = QAction("便捷模式", menu)
        compact_action.triggered.connect(self.mode_router.show_compact)
        pdf_action = QAction("PDF 阅读模式", menu)
        pdf_action.triggered.connect(self.mode_router.show_pdf)
        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(self._open_settings)
        self.review_action = QAction("今日复习", menu)
        self.review_action.triggered.connect(
            lambda: self._ensure_compact_window().open_review()
        )
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show_action)
        menu.addAction(compact_action)
        menu.addAction(pdf_action)
        menu.addSeparator()
        menu.addAction(self.review_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self.mode_router.show_chooser()
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
            self._ensure_compact_window().open_review()

    def _check_review_reminder(self) -> None:
        count = self.repository.due_learning_count()
        self._refresh_review_action(count)
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
            self.mode_router.toggle_compact()
        elif name == "selection":
            pdf_window = self.mode_router.pdf_window
            if (
                pdf_window is not None
                and pdf_window.isVisible()
                and pdf_window.has_active_selection()
            ):
                pdf_window.translate_active_selection()
            else:
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
        if self.main_window is not None:
            self.main_window.status.setText(message)
        self.tray.showMessage("快捷键注册失败", message, QSystemTrayIcon.Warning, 4500)

    def _selection_captured(self, text: str, context: str, x: int, y: int) -> None:
        self.popup.show_query(text, QPoint(x, y))
        main_window = self._ensure_compact_window()
        main_window.input.setPlainText(text)
        main_window._last_auto_text = text
        self.controller.submit(text, context=context)

    def _selection_failed(self, message: str) -> None:
        self._review_message_active = False
        self.tray.showMessage("LinguaSpark", message, QSystemTrayIcon.Warning, 1800)

    def _open_from_popup(self, text: str) -> None:
        self.popup.hide()
        main_window = self.mode_router.show_compact()
        main_window.input.setPlainText(text)

    def run(self) -> int:
        self.hotkeys.start()
        self.review_timer.start()
        if not self.dictionary.available:
            logger.warning("Local dictionary database is missing")
        self.mode_router.show_chooser()
        return self.qt.exec()

    def quit(self) -> None:
        self.hotkeys.stop()
        self.controller.cancel()
        pdf_window = self.mode_router.pdf_window
        if pdf_window is not None:
            pdf_window.close_all_tabs()
        if self.pdf_client is not None:
            self.pdf_client.cancel()
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
