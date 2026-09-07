"""Minimal main experience: input, immediate facts, and progressive AI help."""

from __future__ import annotations

from PySide6.QtCore import (
    QByteArray, QBuffer, QEasingCurve, QIODevice, QPropertyAnimation,
    QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QCloseEvent, QKeyEvent, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import AiStudyNote, DictionaryEntry, QueryKind, QueryRequest, SentenceResult
from learning_assistant.services.autostart import AutostartService
from learning_assistant.services.speech import SpeechProvider
from learning_assistant.ui.result_views import SentenceResultView, WordResultView, text_label
from learning_assistant.ui.settings_dialog import SettingsDialog
from learning_assistant.ui.review_dialog import ReviewDialog


class InputEdit(QPlainTextEdit):
    submit_requested = Signal()
    image_pasted = Signal(bytes)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "JPEG", 88)
            self.image_pasted.emit(bytes(data))
            return
        super().insertFromMimeData(source)


class MainWindow(QMainWindow):
    visibility_requested = Signal(bool)
    review_count_changed = Signal(int)
    settings_opened = Signal()
    settings_closed = Signal()

    def __init__(
        self,
        controller: LearningController,
        settings: SettingsStore,
        speech: SpeechProvider,
        autostart: AutostartService | None = None,
    ):
        super().__init__()
        self.controller = controller
        self.settings = settings
        self.speech = speech
        self.autostart = autostart or AutostartService()
        self.image_bytes: bytes | None = None
        self.current_kind: QueryKind | None = None
        self._last_auto_text = ""
        self._resize_animation: QPropertyAnimation | None = None
        self._review_dialog: ReviewDialog | None = None
        self.setWindowTitle("LinguaSpark · AI 英语学习助手")
        self.resize(580, 292)
        self.setMinimumSize(500, 270)
        self.setMaximumWidth(700)
        self._build_ui()
        self._connect()
        self._reload_models()

        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_lookup)
        self.input.textChanged.connect(self._schedule_auto_lookup)
        QShortcut(QKeySequence("Ctrl+L"), self, self.clear)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(text_label("LinguaSpark", "title", selectable=False))
        title_box.addWidget(text_label("AI 英语学习助手", "muted", selectable=False))
        header.addLayout(title_box)
        header.addStretch(1)
        self.review_button = QPushButton("今日复习 0")
        self.review_button.setObjectName("secondary")
        self.review_button.clicked.connect(self.open_review)
        header.addWidget(self.review_button)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(145)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        header.addWidget(self.model_combo)
        self.settings_button = QToolButton()
        self.settings_button.setText("设置")
        self.settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.settings_button)
        root.addLayout(header)

        self.input_card = QFrame()
        self.input_card.setObjectName("card")
        self.input_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_card.setFixedHeight(200)
        input_layout = QVBoxLayout(self.input_card)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(8)
        input_top = QHBoxLayout()
        input_top.addWidget(text_label("英语 → 中文", "muted", selectable=False))
        input_top.addStretch(1)
        input_top.addWidget(text_label("单词自动查询 · Ctrl+Enter 翻译", "muted", selectable=False))
        input_layout.addLayout(input_top)
        self.input = InputEdit()
        self.input.setPlaceholderText("输入单词或句子，也可以粘贴图片…")
        self.input.setMinimumHeight(84)
        self.input.setMaximumHeight(150)
        self.input.submit_requested.connect(self.submit)
        self.input.image_pasted.connect(self._set_image)
        input_layout.addWidget(self.input)
        self.image_row = QFrame()
        image_layout = QHBoxLayout(self.image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_preview = QLabel()
        self.image_preview.setFixedSize(90, 54)
        self.image_preview.setScaledContents(True)
        image_layout.addWidget(self.image_preview)
        image_layout.addWidget(text_label("已附加图片", "muted", selectable=False))
        image_layout.addStretch(1)
        remove_image = QPushButton("移除")
        remove_image.setObjectName("ghost")
        remove_image.clicked.connect(self._remove_image)
        image_layout.addWidget(remove_image)
        self.image_row.hide()
        input_layout.addWidget(self.image_row)
        input_actions = QHBoxLayout()
        self.status = text_label("就绪", "muted", selectable=False)
        input_actions.addWidget(self.status, 1)
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self.clear)
        self.submit_button = QPushButton("开始学习")
        self.submit_button.setObjectName("primary")
        self.submit_button.clicked.connect(self._submit_or_cancel)
        input_actions.addWidget(self.clear_button)
        input_actions.addWidget(self.submit_button)
        input_layout.addLayout(input_actions)
        root.addWidget(self.input_card)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.stack = QStackedWidget()
        self.empty_view = QFrame()
        self.empty_view.setObjectName("card")
        empty_layout = QVBoxLayout(self.empty_view)
        empty_layout.addStretch(1)
        empty_title = text_label("从一个单词开始", "title", selectable=False)
        empty_title.setAlignment(Qt.AlignCenter)
        empty_hint = text_label("本地词典先给出基础信息，AI 随后补充语境、搭配和记忆提示。", "muted", selectable=False)
        empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch(1)
        self.word_view = WordResultView()
        self.sentence_view = SentenceResultView()
        self.error_view = QFrame()
        self.error_view.setObjectName("card")
        error_layout = QVBoxLayout(self.error_view)
        self.error_label = text_label()
        self.error_label.setAlignment(Qt.AlignCenter)
        error_layout.addStretch(1)
        error_layout.addWidget(self.error_label)
        error_layout.addStretch(1)
        for widget in (self.empty_view, self.word_view, self.sentence_view, self.error_view):
            self.stack.addWidget(widget)
        self.scroll.setWidget(self.stack)
        self.scroll.hide()
        root.addWidget(self.scroll, 1)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.controller.query_started.connect(self._on_started)
        self.controller.word_ready.connect(self._on_word)
        self.controller.ai_note_ready.connect(self._on_note)
        self.controller.sentence_ready.connect(self._on_sentence)
        self.controller.query_failed.connect(self._on_error)
        self.controller.query_finished.connect(self._on_finished)
        self.controller.favorite_changed.connect(self._set_favorite)
        self.controller.study_changed.connect(self._set_study)
        self.word_view.speak_requested.connect(self._speak)
        self.word_view.copy_requested.connect(self._copy_text)
        self.word_view.favorite_requested.connect(self.controller.toggle_favorite)
        self.word_view.study_requested.connect(self._toggle_study)
        self.sentence_view.speak_requested.connect(self._speak)
        self.sentence_view.copy_requested.connect(self._copy_text)
        self.sentence_view.favorite_requested.connect(self.controller.toggle_favorite)
        self.speech.failed.connect(lambda message: self.status.setText(message))
        self.refresh_review_count()

    def _schedule_auto_lookup(self) -> None:
        text = self.input.toPlainText().strip()
        if self.image_bytes or not self.controller.dictionary.is_word(text):
            self.auto_timer.stop()
            return
        delay = int(self.settings.get("auto_lookup_delay_ms", 160))
        self.auto_timer.start(max(80, delay))

    def _auto_lookup(self) -> None:
        text = self.input.toPlainText().strip()
        if text and text != self._last_auto_text and self.controller.dictionary.is_word(text):
            self._last_auto_text = text
            self.submit()

    def _submit_or_cancel(self) -> None:
        if self.submit_button.text() == "停止":
            self.controller.cancel()
        else:
            self.submit()

    def submit(self) -> None:
        self.controller.submit(self.input.toPlainText(), image_bytes=self.image_bytes)

    def submit_selection(self, text: str, context: str = "") -> None:
        self.input.setPlainText(text)
        self._last_auto_text = text
        self.controller.submit(text, context=context)

    def _on_started(self, request: QueryRequest) -> None:
        self.current_kind = request.kind
        self.submit_button.setText("停止")
        self.status.setText("正在处理…")
        self.scroll.hide()
        self._resize_to(292)
        if request.kind == QueryKind.WORD:
            self.word_view.show_query(request.text)
            self.stack.setCurrentWidget(self.word_view)
        else:
            self.sentence_view.set_source(request.text)
            self.sentence_view.translation.setText("AI 正在翻译…")
            self.sentence_view.phrases.hide()
            self.sentence_view.tip.hide()
            self.stack.setCurrentWidget(self.sentence_view)

    def _on_word(self, entry: DictionaryEntry, elapsed_ms: int) -> None:
        self.word_view.show_entry(entry)
        self.word_view.set_favorite(self.controller.is_current_favorite())
        self.word_view.set_study(self.controller.is_current_study())
        self.status.setText(f"本地词典 · {elapsed_ms} ms")
        self.scroll.show()
        self._resize_to(535)

    def _on_note(self, note: AiStudyNote, cache_hit: bool) -> None:
        self.word_view.show_note(note)
        self.status.setText("AI 助学 · 缓存" if cache_hit else "AI 助学已完成")
        self.scroll.show()
        self._resize_to(720)

    def _on_sentence(self, result: SentenceResult, cache_hit: bool) -> None:
        self.sentence_view.show_result(result)
        self.sentence_view.set_favorite(self.controller.is_current_favorite())
        self.status.setText("翻译结果 · 缓存" if cache_hit else "翻译已完成")
        self.scroll.show()
        self._resize_to(530)

    def _on_error(self, message: str) -> None:
        self.submit_button.setText("开始学习")
        if self.current_kind == QueryKind.WORD and self.word_view.entry:
            self.word_view.show_ai_error(message)
        else:
            self.error_label.setText(message)
            self.stack.setCurrentWidget(self.error_view)
            self.scroll.show()
            self._resize_to(410)
        self.status.setText(message)

    def _on_finished(self, info: object) -> None:
        self.submit_button.setText("开始学习")

    def _set_favorite(self, active: bool) -> None:
        if self.current_kind == QueryKind.WORD:
            self.word_view.set_favorite(active)
        else:
            self.sentence_view.set_favorite(active)

    def _toggle_study(self) -> None:
        self.controller.toggle_study()
        self.refresh_review_count()

    def _set_study(self, active: bool) -> None:
        self.word_view.set_study(active)
        self.refresh_review_count()

    def refresh_review_count(self) -> int:
        count = self.controller.repository.due_learning_count()
        self.review_button.setText(f"今日复习 {count}")
        self.review_count_changed.emit(count)
        return count

    def open_review(self) -> None:
        if self._review_dialog is None:
            self._review_dialog = ReviewDialog(
                self.controller.repository, self.speech, self.settings, self
            )
            self._review_dialog.queue_changed.connect(self.refresh_review_count)
        self._review_dialog.reload()
        self._review_dialog.show()
        self._review_dialog.raise_()
        self._review_dialog.activateWindow()

    def _speak(self, text: str) -> None:
        locale = str(self.settings.get("tts", {}).get("voice_locale", "en-US"))
        if self.speech.speak(text, locale):
            self.status.setText("正在朗读…")

    def _set_image(self, data: bytes) -> None:
        self.image_bytes = data
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.image_preview.setPixmap(pixmap)
        self.image_row.show()
        self.input_card.setFixedHeight(260)
        self.status.setText("图片已附加，按 Ctrl+Enter 开始识别")
        self._resize_to(350)

    def _remove_image(self) -> None:
        self.image_bytes = None
        self.image_preview.clear()
        self.image_row.hide()
        self.input_card.setFixedHeight(200)

    def clear(self) -> None:
        self.controller.cancel()
        self.input.clear()
        self._remove_image()
        self._last_auto_text = ""
        self.stack.setCurrentWidget(self.empty_view)
        self.scroll.hide()
        self.status.setText("就绪")
        self.submit_button.setText("开始学习")
        self._resize_to(292)

    def _resize_to(self, requested_height: int) -> None:
        """Grow downward as results arrive and collapse back after clearing."""
        screen = self.screen() or QApplication.primaryScreen()
        maximum = screen.availableGeometry().bottom() - self.frameGeometry().top() - 12
        target_height = max(self.minimumHeight(), min(requested_height, maximum))
        target = QSize(self.width(), target_height)
        if self.size() == target:
            return
        if self._resize_animation:
            self._resize_animation.stop()
        animation = QPropertyAnimation(self, b"size", self)
        animation.setDuration(180)
        animation.setStartValue(self.size())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()
        self._resize_animation = animation

    def copy_result(self) -> None:
        text = self.word_view.plain_text() if self.current_kind == QueryKind.WORD else self.sentence_view.plain_text()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status.setText("已复制")

    def _copy_text(self, text: str) -> None:
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status.setText("已复制")

    def _reload_models(self) -> None:
        active = self.settings.get("active_model_id", "")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for profile in self.settings.models():
            self.model_combo.addItem(profile.name or profile.model, profile.id)
        index = self.model_combo.findData(active)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)

    def _model_changed(self, index: int) -> None:
        identifier = self.model_combo.itemData(index)
        if identifier:
            self.settings.select_model(str(identifier))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self, autostart=self.autostart)
        dialog.settings_changed.connect(self._reload_models)
        self.settings_opened.emit()
        try:
            dialog.exec()
            self._reload_models()
        finally:
            self.settings_closed.emit()

    def show_front(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_front()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
