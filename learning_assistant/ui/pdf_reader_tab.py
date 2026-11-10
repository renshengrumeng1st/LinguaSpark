"""One self-contained PDF document reading and translation session."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut

from learning_assistant.core.settings import DEFAULT_SETTINGS, SettingsStore
from learning_assistant.domain.pdf_models import PdfPhrase, PdfTranslationResult
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.services.selection import GlobalHotkeyService
from learning_assistant.ui.pdf_themes import READING_THEMES

if TYPE_CHECKING:
    from learning_assistant.ui.pdfjs_view import PdfJsViewAdapter


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
        self._learning_result_ready = False
        self.phrase_buttons: dict[PdfPhrase, QPushButton] = {}
        self._build_ui()
        self._connect()
        self.set_theme(str(settings.get("pdf", {}).get("theme", "eye_care")))

    def _build_ui(self) -> None:
        from learning_assistant.ui.pdfjs_view import PdfJsViewAdapter

        self.setObjectName("pdfReaderTab")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.pdf_view = PdfJsViewAdapter()
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
        phrase_scroll = QScrollArea()
        phrase_scroll.setWidgetResizable(True)
        phrase_scroll.setMaximumHeight(220)
        phrase_scroll.setMinimumHeight(100)
        phrase_scroll.setFrameShape(QFrame.NoFrame)
        self.phrase_list = QWidget()
        self.phrase_list_layout = QVBoxLayout(self.phrase_list)
        self.phrase_list_layout.setContentsMargins(0, 0, 0, 0)
        self.phrase_list_layout.setSpacing(10)
        phrase_scroll.setWidget(self.phrase_list)
        phrase_layout.addWidget(phrase_scroll)
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
        self.highlight_combo.setToolTip(
            "可先选择颜色，再选中文字并标记。修改已有标记时，重新选中同一段原文后再标记。"
        )
        self.highlight_button = QPushButton("标记")
        self.remove_highlight_button = QPushButton("移除标记")
        # Parent shortcuts to the document tab so hidden tabs cannot handle them,
        # and they also work when the PDF view has keyboard focus.
        self._highlight_shortcut = QShortcut(QKeySequence(), self)
        self._remove_highlight_shortcut = QShortcut(QKeySequence(), self)
        for shortcut, button in (
            (self._highlight_shortcut, self.highlight_button),
            (self._remove_highlight_shortcut, self.remove_highlight_button),
        ):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(button.click)
        self.reload_shortcuts()
        mark_actions.addWidget(self.highlight_combo)
        mark_actions.addWidget(self.highlight_button)
        mark_actions.addWidget(self.remove_highlight_button)
        mark_actions.addStretch(1)
        right.addLayout(mark_actions)

        self.splitter.addWidget(self.translation_panel)
        self._splitter_handle = self.splitter.handle(1)
        self._splitter_handle.installEventFilter(self)
        self.splitter.setStretchFactor(0, 65)
        self.splitter.setStretchFactor(1, 35)
        self.splitter.setSizes([650, 350])
        root.addWidget(self.splitter)
        self._set_selection_actions_enabled(False)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._splitter_handle and isinstance(event, QMouseEvent):
            dragging = (
                event.type() == QEvent.Type.MouseMove
                and bool(event.buttons() & Qt.MouseButton.LeftButton)
            )
            drag_boundary = (
                event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
                and event.button() == Qt.MouseButton.LeftButton
            )
            if dragging or drag_boundary:
                # Run before QSplitter applies the new width: capturing after
                # splitterMoved could already include an unpainted black edge.
                self.pdf_view.begin_viewport_transition()
        return super().eventFilter(watched, event)

    def _connect(self) -> None:
        self.translate_button.clicked.connect(self.translate_active_selection)
        self.copy_button.clicked.connect(self._copy_translation)
        self.highlight_button.clicked.connect(self._add_highlight)
        self.remove_highlight_button.clicked.connect(self._remove_highlight)
        self.pdf_view.selection_changed.connect(self._selection_changed)
        self.pdf_view.document_loaded.connect(self._document_loaded)
        self.pdf_view.load_failed.connect(self.status.setText)
        self.pdf_view.selection_feedback.connect(self.status.setText)
        self.controller.translation_started.connect(self._translation_started)
        self.controller.translation_partial.connect(self._translation_partial)
        self.controller.phrase_ready.connect(self._phrase_ready)
        self.controller.translation_completed.connect(
            self._translation_completed
        )
        self.controller.translation_failed.connect(self._translation_failed)
        self.controller.annotations_changed.connect(self.pdf_view.set_annotations)
        self.controller.selection_changed.connect(self._apply_selection)
        self.controller.learning_changed.connect(self._refresh_learning_buttons)
        self.controller.learning_failed.connect(self.status.setText)

    def reload_shortcuts(self) -> None:
        for key, shortcut, button, label in (
            ("pdf_highlight_hotkey", self._highlight_shortcut,
             self.highlight_button, "标记选中文字"),
            ("pdf_remove_highlight_hotkey", self._remove_highlight_shortcut,
             self.remove_highlight_button, "移除当前选区的标记"),
        ):
            try:
                binding = GlobalHotkeyService.format_binding(
                    str(self.settings.get(key, DEFAULT_SETTINGS[key]))
                )
            except ValueError:
                binding = GlobalHotkeyService.format_binding(DEFAULT_SETTINGS[key])
            # The recorder uses Windows labels; Qt calls the Win modifier Meta.
            shortcut.setKey(QKeySequence(binding.replace("Win+", "Meta+")))
            button.setToolTip(f"{label}（{binding}）")

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
            QWidget#pdfReaderTab QLabel,
            QWidget#pdfReaderTab QPlainTextEdit {{ color: #1f2937; }}
            QFrame#translationPanel {{
                background-color: {color};
                border: 1px solid rgba(107, 114, 128, 45);
                border-radius: 12px;
            }}
            QFrame#phrasePanel {{
                background: rgba(255, 255, 255, 150);
                border: 1px solid rgba(107, 114, 128, 35);
                border-radius: 8px;
            }}
            QWidget#pdfReaderTab QLabel#pdfStatus {{ color: #6b7280; }}
            """
        )

    def _document_loaded(self, document_key: str, _page_count: int) -> None:
        self.controller.set_selection(None, document_key)
        self.pdf_view.set_annotations(self.controller.annotations())

    def _selection_changed(self, selection) -> None:
        self.controller.set_selection(selection, self.pdf_view.document_key)

    def _apply_selection(self, selection) -> None:
        self._learning_result_ready = False
        self._phrases.clear()
        self._render_phrases()
        active = selection is not None
        self._set_selection_actions_enabled(active)
        if not active:
            self.source.clear()
            self.status.setText("请拖动选择一段文字")
            return
        self._set_selection_actions_enabled(True, selection.can_annotate)
        self.source.setPlainText(selection.text)
        self.status.setText(
            "已选择 · 按 Alt+W 翻译"
            if selection.can_annotate
            else "已选择 · 可翻译，跨页选区暂不支持标记"
        )

    def _set_selection_actions_enabled(
        self,
        enabled: bool,
        can_annotate: bool | None = None,
    ) -> None:
        self.translate_button.setEnabled(enabled)
        marking_enabled = enabled and (
            True if can_annotate is None else can_annotate
        )
        for widget in (
            self.highlight_button,
            self.remove_highlight_button,
        ):
            widget.setEnabled(marking_enabled)

    def has_active_selection(self) -> bool:
        return self.controller.selection is not None

    def translate_active_selection(self) -> None:
        self.controller.translate_selection()

    def _translation_started(self, source: str) -> None:
        self.source.setPlainText(source)
        self.translation.setPlainText("正在翻译…")
        self._waiting_for_first_token = True
        self._phrases.clear()
        self._learning_result_ready = False
        self._render_phrases()
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
        self.phrase_buttons.clear()
        while self.phrase_list_layout.count():
            item = self.phrase_list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for phrase in self._phrases:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            content = QVBoxLayout()
            for text in (phrase.source, phrase.meaning):
                label = QLabel(text)
                label.setWordWrap(True)
                label.setTextFormat(Qt.PlainText)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                content.addWidget(label)
            layout.addLayout(content, 1)
            button = QPushButton("加入学习")
            button.setObjectName("secondary")
            button.setToolTip("保存词组、原句与 PDF 页码，之后可在复习中返回原文。")
            button.clicked.connect(lambda _checked=False, current=phrase: self._add_phrase_to_learning(current))
            layout.addWidget(button)
            self.phrase_buttons[phrase] = button
            self.phrase_list_layout.addWidget(row)
        self._refresh_learning_buttons()
        self.phrase_panel.setVisible(bool(self._phrases))

    def _refresh_learning_buttons(self) -> None:
        for phrase, button in self.phrase_buttons.items():
            exists = self.controller.is_phrase_in_learning(phrase)
            button.setText("已加入学习" if exists else "加入学习")
            button.setEnabled(self._learning_result_ready and not exists)

    def _add_phrase_to_learning(self, phrase: PdfPhrase) -> None:
        if not self._learning_result_ready:
            return
        if self.controller.add_phrase_to_learning(phrase, self.document_path):
            self._refresh_learning_buttons()
            self.status.setText("已加入学习 · 可在复习中返回来源 PDF")

    def _translation_completed(
        self, result: PdfTranslationResult, cache_hit: bool
    ) -> None:
        self.translation.setPlainText(result.translation)
        self._waiting_for_first_token = False
        self._phrases = list(result.phrases)
        self._learning_result_ready = True
        self._render_phrases()
        self.status.setText("翻译完成 · 缓存" if cache_hit else "翻译完成")

    def _translation_failed(self, message: str) -> None:
        if self._waiting_for_first_token:
            self.translation.clear()
        self._waiting_for_first_token = False
        self._learning_result_ready = False
        self._refresh_learning_buttons()
        self.status.setText(message)

    def _add_highlight(self) -> None:
        color = str(self.highlight_combo.currentData() or "yellow")
        self.controller.add_highlight(color)

    def _remove_highlight(self) -> None:
        if self.controller.delete_highlight():
            self.pdf_view.clear_selection()
            self.status.setText("标记已移除")
            return
        self.status.setText("当前选区没有可移除的标记")

    def _copy_translation(self) -> None:
        text = self.translation.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("译文已复制")

    @staticmethod
    def clipboard_text() -> str:
        return QApplication.clipboard().text()
