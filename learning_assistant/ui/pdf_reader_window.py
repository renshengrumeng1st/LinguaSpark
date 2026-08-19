"""Multi-document PDF reader window."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from learning_assistant.core.settings import SettingsStore
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.ui.pdf_reader_tab import PdfReaderTab


THEME_NAMES = {
    "eye_care": "淡绿护眼",
    "paper": "米黄纸张",
    "soft_gray": "柔和灰",
    "white": "纯白",
}


class PdfReaderWindow(QMainWindow):
    """Manage independent PDF sessions and route global reader actions."""

    compact_mode_requested = Signal()
    settings_requested = Signal()

    def __init__(
        self,
        settings: SettingsStore,
        controller_factory: Callable[[], PdfTranslationController],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._controller_factory = controller_factory
        self._tabs_by_path: dict[str, PdfReaderTab] = {}
        self._focus_mode = False
        self.setWindowTitle("LinguaSpark · PDF 阅读模式")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._connect()
        self._load_pdf_preferences()
        self._sync_empty_state()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("pdfWorkspace")
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        self.toolbar_widget = QFrame()
        toolbar = QHBoxLayout(self.toolbar_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        title = QLabel("PDF 阅读")
        title.setObjectName("pdfTitle")
        toolbar.addWidget(title)
        self.open_button = QPushButton("打开 PDF")
        self.open_button.setObjectName("primary")
        toolbar.addWidget(self.open_button)
        self.compact_button = QPushButton("便捷模式")
        self.compact_button.setObjectName("secondary")
        toolbar.addWidget(self.compact_button)
        self.focus_button = QPushButton("专注阅读")
        self.focus_button.setObjectName("secondary")
        toolbar.addWidget(self.focus_button)
        toolbar.addStretch(1)
        self.zoom_out_button = QToolButton()
        self.zoom_out_button.setText("−")
        self.zoom_out_button.setToolTip("缩小（Ctrl + 滚轮）")
        toolbar.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(46)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.zoom_label)
        self.zoom_in_button = QToolButton()
        self.zoom_in_button.setText("+")
        self.zoom_in_button.setToolTip("放大（Ctrl + 滚轮）")
        toolbar.addWidget(self.zoom_in_button)
        self.fit_width_button = QPushButton("适合宽度")
        self.fit_width_button.setObjectName("secondary")
        toolbar.addWidget(self.fit_width_button)
        toolbar.addWidget(QLabel("背景"))
        self.theme_combo = QComboBox()
        for theme_id, name in THEME_NAMES.items():
            self.theme_combo.addItem(name, theme_id)
        toolbar.addWidget(self.theme_combo)
        self.settings_button = QToolButton()
        self.settings_button.setText("设置")
        toolbar.addWidget(self.settings_button)
        root.addWidget(self.toolbar_widget)

        self.content_stack = QStackedWidget()
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.addStretch(1)
        empty_title = QLabel("打开 PDF，开始专注阅读")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        self.empty_open_button = QPushButton("打开 PDF")
        self.empty_open_button.setObjectName("primary")
        self.empty_open_button.setMaximumWidth(180)
        empty_layout.addWidget(
            self.empty_open_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.global_status = QLabel("")
        self.global_status.setObjectName("pdfStatus")
        self.global_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.global_status)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(self.empty_state)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.content_stack.addWidget(self.tab_widget)
        root.addWidget(self.content_stack, 1)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.open_button.clicked.connect(lambda: self.open_files())
        self.empty_open_button.clicked.connect(lambda: self.open_files())
        self.compact_button.clicked.connect(self.compact_mode_requested)
        self.focus_button.clicked.connect(self.enter_focus_mode)
        self.settings_button.clicked.connect(self.settings_requested)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.zoom_out_button.clicked.connect(lambda: self.adjust_active_zoom(-1))
        self.zoom_in_button.clicked.connect(lambda: self.adjust_active_zoom(1))
        self.fit_width_button.clicked.connect(self.fit_active_width)
        self.tab_widget.currentChanged.connect(self._current_changed)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return str(Path(path).resolve()).casefold()

    def open_files(self, paths: Iterable[str | Path] | None = None) -> int:
        selected_paths = list(paths or [])
        if not selected_paths:
            last_dir = str(self.settings.get("pdf", {}).get("last_directory", ""))
            selected, _ = QFileDialog.getOpenFileNames(
                self, "打开 PDF", last_dir, "PDF 文件 (*.pdf)"
            )
            selected_paths = selected
        opened = 0
        for path in selected_paths:
            opened += int(self.open_file(path))
        return opened

    def open_file(self, path: str | Path | None = None) -> bool:
        if path is None:
            return bool(self.open_files())
        resolved = Path(path).resolve()
        key = self._path_key(resolved)
        existing = self._tabs_by_path.get(key)
        if existing is not None:
            self.tab_widget.setCurrentWidget(existing)
            return True

        controller = self._controller_factory()
        tab = PdfReaderTab(controller, self.settings)
        tab.set_theme(str(self.theme_combo.currentData() or "eye_care"))
        if not tab.load_file(resolved):
            self.global_status.setText(tab.status.text() or "无法打开此 PDF")
            tab.close_session()
            tab.deleteLater()
            self._sync_empty_state()
            return False

        tab.pdf_view.zoomFactorChanged.connect(
            lambda factor, source=tab: self._tab_zoom_changed(source, factor)
        )
        index = self.tab_widget.addTab(tab, resolved.name)
        self.tab_widget.setTabToolTip(index, str(resolved))
        self._tabs_by_path[key] = tab
        self.tab_widget.setCurrentIndex(index)
        pdf = dict(self.settings.get("pdf", {}))
        pdf["last_directory"] = str(resolved.parent)
        self.settings.set("pdf", pdf)
        self.settings.save()
        self.global_status.clear()
        self._sync_empty_state()
        return True

    def current_tab(self) -> PdfReaderTab | None:
        widget = self.tab_widget.currentWidget()
        return widget if isinstance(widget, PdfReaderTab) else None

    def close_tab(self, index: int) -> None:
        widget = self.tab_widget.widget(index)
        if not isinstance(widget, PdfReaderTab):
            return
        self._tabs_by_path.pop(self._path_key(widget.document_path), None)
        widget.close_session()
        self.tab_widget.removeTab(index)
        widget.deleteLater()
        self._sync_empty_state()

    def close_all_tabs(self) -> None:
        while self.tab_widget.count():
            self.close_tab(self.tab_widget.count() - 1)

    def _sync_empty_state(self) -> None:
        has_tabs = self.tab_widget.count() > 0
        self.content_stack.setCurrentWidget(
            self.tab_widget if has_tabs else self.empty_state
        )
        for control in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_width_button,
            self.focus_button,
        ):
            control.setEnabled(has_tabs)
        if not has_tabs:
            self.zoom_label.setText("100%")

    def _current_changed(self, _index: int) -> None:
        tab = self.current_tab()
        if tab is not None:
            self._zoom_changed(tab.pdf_view.zoomFactor())

    def _tab_zoom_changed(self, tab: PdfReaderTab, factor: float) -> None:
        if tab is self.current_tab():
            self._zoom_changed(factor)

    def adjust_active_zoom(self, steps: int) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.pdf_view.adjust_zoom(steps)

    def fit_active_width(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.pdf_view.fit_to_width()

    def _zoom_changed(self, factor: float) -> None:
        self.zoom_label.setText(f"{round(factor * 100):d}%")

    def _load_pdf_preferences(self) -> None:
        theme = str(self.settings.get("pdf", {}).get("theme", "eye_care"))
        index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self._apply_theme(str(self.theme_combo.currentData()))

    def _theme_changed(self, _index: int) -> None:
        theme = str(self.theme_combo.currentData() or "eye_care")
        self._apply_theme(theme)
        pdf = dict(self.settings.get("pdf", {}))
        pdf["theme"] = theme
        self.settings.set("pdf", pdf)
        self.settings.save()

    def _apply_theme(self, theme: str) -> None:
        for index in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(index)
            if isinstance(tab, PdfReaderTab):
                tab.set_theme(theme)
        self.centralWidget().setStyleSheet(
            """
            QLabel#pdfTitle { font-size: 20px; font-weight: 700; }
            QLabel#emptyTitle { font-size: 22px; font-weight: 650; color: #374151; }
            QLabel#pdfStatus { color: #6b7280; }
            """
        )

    def has_active_selection(self) -> bool:
        tab = self.current_tab()
        return tab is not None and tab.has_active_selection()

    def translate_active_selection(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.translate_active_selection()

    def enter_focus_mode(self) -> None:
        if self._focus_mode or self.current_tab() is None:
            return
        self._focus_mode = True
        self.toolbar_widget.hide()
        self.tab_widget.tabBar().hide()
        self.showFullScreen()

    def exit_focus_mode(self) -> None:
        if not self._focus_mode:
            return
        self._focus_mode = False
        self.toolbar_widget.show()
        self.tab_widget.tabBar().show()
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._focus_mode and event.key() == Qt.Key.Key_Escape:
            self.exit_focus_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def show_front(self) -> None:
        if self._focus_mode:
            self.showFullScreen()
        else:
            self.showMaximized()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
