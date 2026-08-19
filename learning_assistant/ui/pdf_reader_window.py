"""PDF reader window shell around a single document session."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
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
    """Temporary one-tab window shell; multi-tab orchestration follows."""

    compact_mode_requested = Signal()
    settings_requested = Signal()

    def __init__(
        self,
        controller: PdfTranslationController,
        settings: SettingsStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.setWindowTitle("LinguaSpark · PDF 阅读模式")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._connect()
        self._load_pdf_preferences()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("pdfWorkspace")
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        title = QLabel("PDF 阅读")
        title.setObjectName("pdfTitle")
        toolbar.addWidget(title)
        self.open_button = QPushButton("打开 PDF")
        self.open_button.setObjectName("primary")
        toolbar.addWidget(self.open_button)
        self.compact_button = QPushButton("便捷模式")
        self.compact_button.setObjectName("secondary")
        toolbar.addWidget(self.compact_button)
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
        root.addLayout(toolbar)

        self.reader_tab = PdfReaderTab(self.controller, self.settings)
        root.addWidget(self.reader_tab, 1)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.open_button.clicked.connect(self.open_file)
        self.compact_button.clicked.connect(self.compact_mode_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.zoom_out_button.clicked.connect(lambda: self.pdf_view.adjust_zoom(-1))
        self.zoom_in_button.clicked.connect(lambda: self.pdf_view.adjust_zoom(1))
        self.fit_width_button.clicked.connect(self.pdf_view.fit_to_width)
        self.pdf_view.zoomFactorChanged.connect(self._zoom_changed)

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
        self.reader_tab.set_theme(theme)
        self.centralWidget().setStyleSheet(
            "QLabel#pdfTitle { font-size: 20px; font-weight: 700; }"
        )

    def open_file(self, path: str | Path | None = None) -> bool:
        selected = str(path) if path else ""
        if not selected:
            last_dir = str(self.settings.get("pdf", {}).get("last_directory", ""))
            selected, _ = QFileDialog.getOpenFileName(
                self, "打开 PDF", last_dir, "PDF 文件 (*.pdf)"
            )
        if not selected or not self.reader_tab.load_file(selected):
            return False
        pdf = dict(self.settings.get("pdf", {}))
        pdf["last_directory"] = str(Path(selected).resolve().parent)
        self.settings.set("pdf", pdf)
        self.settings.save()
        return True

    def _zoom_changed(self, factor: float) -> None:
        self.zoom_label.setText(f"{round(factor * 100):d}%")

    def has_active_selection(self) -> bool:
        return self.reader_tab.has_active_selection()

    def translate_active_selection(self) -> None:
        self.reader_tab.translate_active_selection()

    def show_front(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    @property
    def splitter(self):
        return self.reader_tab.splitter

    @property
    def pdf_view(self):
        return self.reader_tab.pdf_view

    @property
    def phrase_panel(self):
        return self.reader_tab.phrase_panel

    @property
    def phrase_text(self):
        return self.reader_tab.phrase_text

    @property
    def translation(self):
        return self.reader_tab.translation

    @property
    def status(self):
        return self.reader_tab.status

    @property
    def highlight_combo(self):
        return self.reader_tab.highlight_combo

    @property
    def highlight_button(self):
        return self.reader_tab.highlight_button

    @property
    def remove_highlight_button(self):
        return self.reader_tab.remove_highlight_button

    @property
    def copy_button(self):
        return self.reader_tab.copy_button

    @staticmethod
    def clipboard_text() -> str:
        return PdfReaderTab.clipboard_text()
