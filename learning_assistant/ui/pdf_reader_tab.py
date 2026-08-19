"""One self-contained PDF document reading and translation session."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.pdf_models import PdfPhrase, PdfTranslationResult
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.ui.pdf_view import READING_THEMES, SelectablePdfView


class PdfReaderTab(QWidget):
    """Own the complete UI and controller lifecycle for one PDF document."""

    def __init__(
        self,
        controller: PdfTranslationController,
        settings: SettingsStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.document_path = ""
        self._phrases: list[PdfPhrase] = []
        self._waiting_for_first_token = False
        self._closed = False
        self._build_ui()
        self._connect()
        self.set_theme(str(settings.get("pdf", {}).get("theme", "eye_care")))

    def _build_ui(self) -> None:
        self.setObjectName("pdfReaderTab")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.pdf_view = SelectablePdfView()
        self.pdf_view.setObjectName("pdfDocument")
        self.pdf_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.splitter.addWidget(self.pdf_view)

        self.translation_panel = QFrame()
        self.translation_panel.setObjectName("translationPanel")
        right = QVBoxLayout(self.translation_panel)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)

        heading = QHBoxLayout()
        heading.addWidget(QLabel("选中内容翻译"))
        heading.addStretch(1)
        self.status = QLabel("请打开 PDF 并选择句子")
        self.status.setObjectName("pdfStatus")
        heading.addWidget(self.status)
        right.addLayout(heading)

        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.source.setPlaceholderText("选中的原文会显示在这里")
        self.source.setMaximumHeight(120)
        right.addWidget(self.source)

        self.translation = QPlainTextEdit()
        self.translation.setReadOnly(True)
        self.translation.setPlaceholderText("按 Alt+W 获取快速翻译")
        right.addWidget(self.translation, 1)

        self.phrase_panel = QFrame()
        self.phrase_panel.setObjectName("phrasePanel")
        phrase_layout = QVBoxLayout(self.phrase_panel)
        phrase_layout.setContentsMargins(12, 10, 12, 10)
        phrase_layout.addWidget(QLabel("词组分析"))
        self.phrase_text = QPlainTextEdit()
        self.phrase_text.setReadOnly(True)
        self.phrase_text.setMaximumHeight(150)
        phrase_layout.addWidget(self.phrase_text)
        self.phrase_panel.hide()
        right.addWidget(self.phrase_panel)

        primary_actions = QHBoxLayout()
        self.translate_button = QPushButton("翻译  Alt+W")
        self.translate_button.setObjectName("primary")
        self.copy_button = QPushButton("复制译文")
        primary_actions.addWidget(self.translate_button)
        primary_actions.addWidget(self.copy_button)
        primary_actions.addStretch(1)
        right.addLayout(primary_actions)

        mark_actions = QHBoxLayout()
        self.highlight_combo = QComboBox()
        self.highlight_combo.addItem("黄色标记", "yellow")
        self.highlight_combo.addItem("绿色标记", "green")
        self.highlight_combo.addItem("粉色标记", "pink")
        self.highlight_button = QPushButton("标记")
        self.remove_highlight_button = QPushButton("移除标记")
        mark_actions.addWidget(self.highlight_combo)
        mark_actions.addWidget(self.highlight_button)
        mark_actions.addWidget(self.remove_highlight_button)
        mark_actions.addStretch(1)
        right.addLayout(mark_actions)

        self.splitter.addWidget(self.translation_panel)
        self.splitter.setStretchFactor(0, 65)
        self.splitter.setStretchFactor(1, 35)
        self.splitter.setSizes([650, 350])
        root.addWidget(self.splitter)
        self._set_selection_actions_enabled(False)

    def _connect(self) -> None:
        self.translate_button.clicked.connect(self.translate_active_selection)
        self.copy_button.clicked.connect(self._copy_translation)
        self.highlight_button.clicked.connect(self._add_highlight)
        self.remove_highlight_button.clicked.connect(
            self.controller.delete_highlight
        )
        self.pdf_view.selection_changed.connect(self._selection_changed)
        self.pdf_view.document_loaded.connect(self._document_loaded)
        self.pdf_view.load_failed.connect(self.status.setText)
        self.controller.translation_started.connect(self._translation_started)
        self.controller.translation_partial.connect(self._translation_partial)
        self.controller.phrase_ready.connect(self._phrase_ready)
        self.controller.translation_completed.connect(
            self._translation_completed
        )
        self.controller.translation_failed.connect(self._translation_failed)
        self.controller.annotations_changed.connect(self.pdf_view.set_annotations)

    def load_file(self, path: str | Path) -> bool:
        resolved = str(Path(path).resolve())
        if not self.pdf_view.load_file(resolved):
            return False
        self.document_path = resolved
        self.status.setText("拖动选择句子，然后按 Alt+W")
        return True

    def close_session(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.pdf_view.close_document()
        self.controller.dispose()

    def set_theme(self, theme: str) -> None:
        theme = theme if theme in READING_THEMES else "eye_care"
        color = READING_THEMES[theme]
        self.pdf_view.set_reading_theme(theme)
        self.setStyleSheet(
            f"""
            QWidget#pdfReaderTab {{ background: {color}; color: #1f2937; }}
            QFrame#translationPanel {{
                background: rgba(255, 255, 255, 210);
                border: 1px solid rgba(107, 114, 128, 45);
                border-radius: 12px;
            }}
            QFrame#phrasePanel {{
                background: rgba(255, 255, 255, 150);
                border: 1px solid rgba(107, 114, 128, 35);
                border-radius: 8px;
            }}
            QLabel#pdfStatus {{ color: #6b7280; }}
            """
        )

    def _document_loaded(self, document_key: str, _page_count: int) -> None:
        self.controller.set_selection(None, document_key)
        self.pdf_view.set_annotations(self.controller.annotations())

    def _selection_changed(self, selection) -> None:
        self.controller.set_selection(selection, self.pdf_view.document_key)
        active = selection is not None
        self._set_selection_actions_enabled(active)
        if not active:
            self.source.clear()
            self.status.setText("请拖动选择一段文字")
            return
        self.source.setPlainText(selection.text)
        self.status.setText("已选择 · 按 Alt+W 翻译")

    def _set_selection_actions_enabled(self, enabled: bool) -> None:
        for widget in (
            self.translate_button,
            self.highlight_combo,
            self.highlight_button,
            self.remove_highlight_button,
        ):
            widget.setEnabled(enabled)

    def has_active_selection(self) -> bool:
        return self.controller.selection is not None

    def translate_active_selection(self) -> None:
        self.controller.translate_selection()

    def _translation_started(self, source: str) -> None:
        self.source.setPlainText(source)
        self.translation.setPlainText("正在翻译…")
        self._waiting_for_first_token = True
        self._phrases.clear()
        self.phrase_text.clear()
        self.phrase_panel.hide()
        self.status.setText("正在翻译…")

    def _translation_partial(self, text: str) -> None:
        if self._waiting_for_first_token:
            self.translation.clear()
            self._waiting_for_first_token = False
        cursor = self.translation.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.translation.setTextCursor(cursor)
        self.status.setText("正在接收译文…")

    def _phrase_ready(self, phrase: PdfPhrase) -> None:
        if phrase not in self._phrases:
            self._phrases.append(phrase)
        self._render_phrases()

    def _render_phrases(self) -> None:
        self.phrase_text.setPlainText(
            "\n\n".join(
                f"{phrase.source}\n{phrase.meaning}" for phrase in self._phrases
            )
        )
        self.phrase_panel.setVisible(bool(self._phrases))

    def _translation_completed(
        self, result: PdfTranslationResult, cache_hit: bool
    ) -> None:
        self.translation.setPlainText(result.translation)
        self._waiting_for_first_token = False
        self._phrases = list(result.phrases)
        self._render_phrases()
        self.status.setText("翻译完成 · 缓存" if cache_hit else "翻译完成")

    def _translation_failed(self, message: str) -> None:
        if self._waiting_for_first_token:
            self.translation.clear()
        self._waiting_for_first_token = False
        self.status.setText(message)

    def _add_highlight(self) -> None:
        color = str(self.highlight_combo.currentData() or "yellow")
        self.controller.add_highlight(color)

    def _copy_translation(self) -> None:
        text = self.translation.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("译文已复制")

    @staticmethod
    def clipboard_text() -> str:
        return QApplication.clipboard().text()
