"""Minimal main experience: input, immediate facts, and progressive AI help."""

from __future__ import annotations

from PySide6.QtCore import (
    QByteArray, QBuffer, QEasingCurve, QFileInfo, QIODevice, QPropertyAnimation,
    QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QCloseEvent, QImage, QImageReader, QKeyEvent, QPainter, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
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
from learning_assistant.ui.library_dialog import LibraryDialog
from learning_assistant.ui.theme_illustration import ThemeIllustration


class InputEdit(QPlainTextEdit):
    submit_requested = Signal()
    image_pasted = Signal(bytes)
    image_rejected = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _image_file(source) -> str:
        urls = source.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ""
        path = urls[0].toLocalFile()
        formats = {bytes(value).decode("ascii") for value in QImageReader.supportedImageFormats()}
        if QFileInfo(path).suffix().casefold() in formats or QImageReader(path).canRead():
            return path
        return ""

    def canInsertFromMimeData(self, source) -> bool:
        if self.isReadOnly():
            return False
        return bool(source.hasImage() or self._image_file(source) or super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source) -> None:
        path = self._image_file(source) if not source.hasImage() else ""
        if not source.hasImage() and not path:
            super().insertFromMimeData(source)
            return
        if path:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
        else:
            image = source.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
        if not isinstance(image, QImage) or image.isNull():
            self.image_rejected.emit("无法读取图片，请重新复制图片或检查文件是否损坏")
            return
        if image.hasAlphaChannel():
            flattened = QImage(image.size(), QImage.Format_RGB32)
            flattened.fill(Qt.white)
            painter = QPainter(flattened)
            painter.drawImage(0, 0, image)
            painter.end()
            image = flattened
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        saved = image.save(buffer, "JPEG", 88)
        buffer.close()
        if not saved or not data:
            self.image_rejected.emit("图片转换失败，请尝试 PNG 或 JPEG 图片")
            return
        self.image_pasted.emit(bytes(data))


class MainWindow(QMainWindow):
    visibility_requested = Signal(bool)
    review_count_changed = Signal(int)
    settings_opened = Signal()
    settings_closed = Signal()
    pdf_source_requested = Signal(object)

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
        self._last_ai_text = ""
        self._busy = False
        self._word_compact = False
        self._library_dialog: LibraryDialog | None = None
        self._resize_animation: QPropertyAnimation | None = None
        self._review_dialog: ReviewDialog | None = None
        self.setWindowTitle("LinguaSpark · AI 英语学习助手")
        self.resize(620, 450)
        self.setMinimumSize(560, 330)
        self.setMaximumWidth(800)
        self._build_ui()
        self._connect()
        self._reload_models()

        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_lookup)
        self.ai_timer = QTimer(self)
        self.ai_timer.setSingleShot(True)
        self.ai_timer.timeout.connect(self._auto_ai)
        self.input.textChanged.connect(self._schedule_auto_lookup)
        self.auto_ai_checkbox.toggled.connect(self._auto_ai_toggled)
        QShortcut(QKeySequence("Ctrl+L"), self, self.clear)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.brand_title = text_label("LinguaSpark", "title", selectable=False)
        self.brand_subtitle = text_label("AI 英语学习助手", "muted", selectable=False)
        title_box.addWidget(self.brand_title)
        title_box.addWidget(self.brand_subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.review_button = QPushButton("复习 0")
        self.review_button.setObjectName("secondary")
        self.review_button.clicked.connect(self.open_review)
        header.addWidget(self.review_button)
        self.library_button = QPushButton("历史与收藏")
        self.library_button.clicked.connect(self.open_library)
        header.addWidget(self.library_button)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(145)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self.settings_button = QToolButton()
        self.settings_button.setText("设置")
        self.settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.settings_button)
        root.addLayout(header)
        options = QHBoxLayout()
        options.addWidget(self.model_combo, 1)
        self.auto_ai_checkbox = QCheckBox("自动 AI 补充")
        self.auto_ai_checkbox.setChecked(bool(self.settings.get("auto_ai_enabled", True)))
        self.auto_ai_checkbox.setToolTip("本地词典先查询，停止输入后再请求 AI；关闭后仍可手动查询。")
        options.addWidget(self.auto_ai_checkbox)
        root.addLayout(options)

        self.input_card = QFrame()
        self.input_card.setObjectName("card")
        self.input_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_card.setFixedHeight(156)
        input_layout = QVBoxLayout(self.input_card)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(8)
        input_top = QHBoxLayout()
        languages = self.settings.languages()
        names = {"en": "英语", "zh-CN": "中文"}
        self.language_label = text_label(f"{names.get(languages.source, languages.source)} → {names.get(languages.target, languages.target)}", "muted", selectable=False)
        input_top.addWidget(self.language_label)
        input_top.addStretch(1)
        self.input_shortcut_hint = text_label("Ctrl+Enter 立即查询", "muted", selectable=False)
        input_top.addWidget(self.input_shortcut_hint)
        input_layout.addLayout(input_top)
        self.input = InputEdit()
        self.input.setPlaceholderText("输入单词或句子，也可以粘贴图片…")
        self.input.setFixedHeight(44)
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
        self.input.image_rejected.connect(self.status.setText)
        input_actions.addWidget(self.status, 1)
        self.configure_ai_button = QToolButton()
        self.configure_ai_button.setText("配置 AI 模型")
        self.configure_ai_button.clicked.connect(self.open_model_settings)
        input_actions.addWidget(self.configure_ai_button)
        self.retry_button = QPushButton("重试")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        input_actions.addWidget(self.retry_button)
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self.clear)
        self.submit_button = QPushButton("查询单词")
        self.submit_button.setObjectName("primary")
        self.submit_button.clicked.connect(self._submit_or_cancel)
        input_actions.addWidget(self.clear_button)
        input_actions.addWidget(self.submit_button)
        input_layout.addLayout(input_actions)
        root.addWidget(self.input_card)
        self.welcome = QFrame()
        self.welcome.setObjectName("settingsHero")
        welcome_layout = QHBoxLayout(self.welcome)
        welcome_layout.setContentsMargins(12, 0, 18, 0)
        welcome_layout.addWidget(ThemeIllustration())
        welcome_text = QVBoxLayout()
        welcome_text.addWidget(text_label("今天，也发现一点新知", "cardTitle", selectable=False))
        self.availability_label = text_label("", "muted", selectable=False)
        welcome_text.addWidget(self.availability_label)
        self.example_button = QPushButton("试试本地查词：hello")
        self.example_button.setObjectName("secondary")
        self.example_button.setToolTip("只查本地词典，不请求 AI，也不保存历史")
        self.example_button.clicked.connect(self._show_local_example)
        welcome_text.addWidget(self.example_button, 0, Qt.AlignLeft)
        welcome_layout.addLayout(welcome_text, 1)
        root.addWidget(self.welcome)

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
        self.word_view = WordResultView(details_expanded=bool(self.settings.get("learning_details_expanded", False)))
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
        self.controller.ai_partial.connect(self._on_partial)
        self.controller.sentence_ready.connect(self._on_sentence)
        self.controller.query_failed.connect(self._on_error)
        self.controller.query_finished.connect(self._on_finished)
        self.controller.favorite_changed.connect(self._set_favorite)
        self.controller.study_changed.connect(self._set_study)
        self.word_view.speak_requested.connect(self._speak)
        self.word_view.copy_requested.connect(self._copy_text)
        self.word_view.favorite_requested.connect(self.controller.toggle_favorite)
        self.word_view.study_requested.connect(self._toggle_study)
        self.word_view.details_expanded_changed.connect(self._save_details_preference)
        self.sentence_view.speak_requested.connect(self._speak)
        self.sentence_view.copy_requested.connect(self._copy_text)
        self.sentence_view.favorite_requested.connect(self.controller.toggle_favorite)
        self.speech.failed.connect(lambda message: self.status.setText(message))
        self.refresh_review_count()

    def _schedule_auto_lookup(self) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.cancel()
        self._busy = False
        self._last_ai_text = ""
        self.retry_button.hide()
        self._update_input_layout()
        text = self.input.toPlainText().strip()
        if self.image_bytes or not self.controller.dictionary.is_word(text):
            self.auto_timer.stop()
            return
        delay = int(self.settings.get("auto_lookup_delay_ms", 160))
        self.auto_timer.start(max(80, delay))
        if self.auto_ai_checkbox.isChecked() and self._has_usable_ai():
            self.ai_timer.start(max(300, int(self.settings.get("auto_ai_delay_ms", 800)), delay + 150))

    def _auto_lookup(self) -> None:
        text = self.input.toPlainText().strip()
        if text and text != self._last_auto_text and self.controller.dictionary.is_word(text):
            self._last_auto_text = text
            self.controller.submit(text, use_ai=False, save_local_history=False)

    def _auto_ai(self) -> None:
        text = self.input.toPlainText().strip()
        if self._has_usable_ai() and not self.image_bytes and text and text != self._last_ai_text and self.controller.dictionary.is_word(text):
            self.submit(automatic=True)

    def _auto_ai_toggled(self, enabled: bool) -> None:
        self.settings.set("auto_ai_enabled", enabled)
        self.settings.save()
        self.ai_timer.stop()
        if not enabled:
            self.controller.cancel()
        elif self._has_usable_ai() and self.controller.dictionary.is_word(self.input.toPlainText().strip()):
            self.ai_timer.start(max(300, int(self.settings.get("auto_ai_delay_ms", 800))))

    def _update_input_layout(self) -> None:
        text = self.input.toPlainText()
        compact = not text.strip() or self.controller.dictionary.is_word(text.strip())
        result_compact = self._word_compact and compact and bool(text.strip()) and not self.image_bytes
        self.brand_subtitle.setVisible(not result_compact)
        self.brand_title.setObjectName("section" if result_compact else "title")
        self.brand_title.style().unpolish(self.brand_title)
        self.brand_title.style().polish(self.brand_title)
        self.input_shortcut_hint.setVisible(not result_compact)
        root = self.centralWidget().layout()
        root.setContentsMargins(18, 12, 18, 12) if result_compact else root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(8 if result_compact else 12)
        self.input_card.layout().setContentsMargins(12, 8, 12, 8) if result_compact else self.input_card.layout().setContentsMargins(16, 12, 16, 12)
        self.input_card.layout().setSpacing(5 if result_compact else 8)
        input_height = (36 if result_compact else 44) if compact else min(140, 66 + 20 * min(4, text.count("\n") + len(text)//55))
        self.input.setFixedHeight(input_height)
        self.input_card.setFixedHeight((88 if result_compact else 112) + input_height + (64 if self.image_bytes else 0))
        self._set_submit_label()

    def _set_submit_label(self) -> None:
        text = "识别并翻译" if self.image_bytes else ("查询单词" if self.controller.dictionary.is_word(self.input.toPlainText().strip()) or not self.input.toPlainText().strip() else "翻译句子")
        self.submit_button.setText("停止" if self._busy else text)

    def retry(self) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.retry()

    def _submit_or_cancel(self) -> None:
        if self._busy:
            self.controller.cancel()
        else:
            self.submit()

    def submit(self, *, automatic: bool = False) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self._last_auto_text = self.input.toPlainText().strip()
        self._last_ai_text = self._last_auto_text
        self._submit_input(self.input.toPlainText(), image_bytes=self.image_bytes,
                           save_local_history=not automatic)

    def submit_selection(self, text: str, context: str = "") -> None:
        self._remove_image()
        self.input.setPlainText(text)
        self.auto_timer.stop()
        self.ai_timer.stop()
        self._last_auto_text = text
        self._last_ai_text = text
        self._submit_input(text, context=context)

    def _submit_input(self, text: str, **kwargs) -> None:
        if self._has_usable_ai():
            self.controller.submit(text, **kwargs)
        elif not kwargs.get("image_bytes") and self.controller.dictionary.is_word(text.strip()):
            self.controller.submit(text, use_ai=False, **kwargs)
        else:
            self.status.setText("句子翻译和图片识别需要 AI，请先在设置中配置 AI 模型。")
            self.configure_ai_button.show()

    def _show_local_example(self) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.cancel()
        self._remove_image()
        self.input.blockSignals(True)
        self.input.setPlainText("hello")
        self.input.blockSignals(False)
        self._last_auto_text = self._last_ai_text = "hello"
        self._update_input_layout()
        self.controller.submit("hello", use_ai=False, save_local_history=False)
        self.word_view.ai_state.setText("本次示例仅使用本地词典。")

    def _on_started(self, request: QueryRequest) -> None:
        self._busy = True
        self.retry_button.hide()
        self.welcome.hide()
        self.current_kind = request.kind
        self._word_compact = request.kind == QueryKind.WORD
        self._update_input_layout()
        self.submit_button.setText("停止")
        self.status.setText("正在处理…")
        self.scroll.hide()
        self._resize_to(350)
        if request.kind == QueryKind.WORD:
            self.word_view.show_query(request.text)
            self.word_view.set_favorite(self.controller.is_current_favorite())
            self.word_view.set_study(self.controller.is_current_study())
            self.stack.setCurrentWidget(self.word_view)
        else:
            self.sentence_view.set_source(request.text)
            self.sentence_view.set_favorite(self.controller.is_current_favorite())
            self.sentence_view.favorite_button.setEnabled(False)
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

    def _on_partial(self, translation: str) -> None:
        if self.current_kind not in (QueryKind.SENTENCE, QueryKind.IMAGE):
            return
        self.sentence_view.translation.setText(translation)
        self.status.setText("正在生成译文…")
        if not self.scroll.isVisible():
            self.scroll.show()
            self._resize_to(430)

    def _on_sentence(self, result: SentenceResult, cache_hit: bool) -> None:
        self.sentence_view.show_result(result)
        self.sentence_view.set_favorite(self.controller.is_current_favorite())
        self.sentence_view.favorite_button.setEnabled(True)
        self.status.setText("翻译结果 · 缓存" if cache_hit else "翻译已完成")
        self.scroll.show()
        self._resize_to(530)

    def _on_error(self, message: str) -> None:
        self._busy = False
        self._set_submit_label()
        self.retry_button.show()
        if self.current_kind == QueryKind.WORD:
            self.word_view.show_ai_error(message)
            if not self.scroll.isVisible():
                self.scroll.show()
                self._resize_to(535)
        else:
            self.error_label.setText(message)
            self.stack.setCurrentWidget(self.error_view)
            self.scroll.show()
            self._resize_to(410)
        self.status.setText(message)

    def _on_finished(self, info: object) -> None:
        self._busy = False
        self._set_submit_label()
        if isinstance(info, dict) and info.get("local_only"):
            if not self.word_view.entry:
                self.word_view.meanings.setText("本地词典未收录这个词。")
                self.scroll.show()
                self._resize_to(535)
            if not self._has_usable_ai():
                self.word_view.ai_state.setText("本地查词可用；配置 AI 模型后，可补充语境、搭配和例句。")
                self.status.setText("本地查词可用 · AI 待配置")
            else:
                self.word_view.ai_state.setText("本地释义已就绪，AI 将在停止输入后补充。" if self.ai_timer.isActive() else "点击“查询单词”获取 AI 补充。")
        if isinstance(info, dict) and info.get("saved"):
            self.status.setText("已打开本地保存的结果")
            if self.current_kind == QueryKind.WORD and not self.controller._current_payload.get("ai_note"):
                self.word_view.ai_state.setText("此记录仅包含本地释义。")

    def open_library(self) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        if self._library_dialog is None:
            self._library_dialog = LibraryDialog(self.controller.repository, self)
            self._library_dialog.open_requested.connect(self.open_saved)
            self._library_dialog.changed.connect(self._refresh_saved_flags)
        self._library_dialog.reload()
        self._library_dialog.show()
        self._library_dialog.raise_()

    def _refresh_saved_flags(self) -> None:
        self._set_favorite(self.controller.is_current_favorite())

    def open_saved(self, item: dict) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.cancel()
        self._remove_image()
        self.input.blockSignals(True)
        self.input.setPlainText(item["source_text"])
        self.input.blockSignals(False)
        self._last_auto_text = self._last_ai_text = item["source_text"]
        self._update_input_layout()
        self.controller.restore_saved(item)
        self._refresh_saved_flags()

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
        self.review_button.setText(f"复习 {count}")
        self.review_button.setToolTip(f"今日有 {count} 个学习项目等待复习")
        self.review_count_changed.emit(count)
        return count

    def open_review(self) -> None:
        if self._review_dialog is None:
            self._review_dialog = ReviewDialog(
                self.controller.repository, self.speech, self.settings, self
            )
            self._review_dialog.queue_changed.connect(self.refresh_review_count)
            self._review_dialog.pdf_source_requested.connect(self.pdf_source_requested)
        self._review_dialog.reload()
        self._review_dialog.show()
        self._review_dialog.raise_()
        self._review_dialog.activateWindow()

    def _speak(self, text: str) -> None:
        locale = str(self.settings.get("tts", {}).get("voice_locale", "en-US"))
        if self.speech.speak(text, locale):
            self.status.setText("正在朗读…")

    def _set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.status.setText("无法读取图片，请重新复制图片")
            return
        self.image_bytes = data
        self.image_preview.setPixmap(pixmap)
        self.image_row.show()
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.cancel()
        self._update_input_layout()
        self.status.setText("图片已附加，按 Ctrl+Enter 开始识别")
        self._resize_to(350)

    def _remove_image(self) -> None:
        self.image_bytes = None
        self.image_preview.clear()
        self.image_row.hide()
        self._update_input_layout()

    def clear(self) -> None:
        self.auto_timer.stop()
        self.ai_timer.stop()
        self.controller.cancel()
        self._word_compact = False
        self.input.clear()
        self._remove_image()
        self._last_auto_text = ""
        self._last_ai_text = ""
        self.retry_button.hide()
        self.welcome.show()
        self.stack.setCurrentWidget(self.empty_view)
        self.scroll.hide()
        self.status.setText("就绪" if self._has_usable_ai() else "本地查词可用 · AI 待配置")
        self._busy = False
        self._set_submit_label()
        self._resize_to(450)

    def _resize_to(self, requested_height: int) -> None:
        """Grow downward as results arrive and collapse back after clearing."""
        screen = self.screen() or QApplication.primaryScreen()
        maximum = screen.availableGeometry().bottom() - self.frameGeometry().top() - 12
        # Fixed-height input sections cannot be compressed by the root layout.
        # Shrinking below their combined minimum makes later sections overlap.
        content_minimum = self.centralWidget().layout().minimumSize().height()
        target_height = max(self.minimumHeight(), content_minimum, min(requested_height, maximum))
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
        self.model_combo.setPlaceholderText("AI 待配置")
        for profile in self.settings.models():
            self.model_combo.addItem(profile.name or profile.model, profile.id)
        index = self.model_combo.findData(active)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        self._refresh_ai_guidance()

    def _has_usable_ai(self) -> bool:
        profile = self.settings.active_model()
        return bool(profile and profile.enabled and profile.base_url.strip()
                    and profile.model.strip() and profile.api_key.strip())

    def _refresh_ai_guidance(self) -> None:
        ready = self._has_usable_ai()
        self.availability_label.setText(
            "本地查词可用 · AI 已就绪\n输入单词即查，句子和图片也能翻译。" if ready else
            "本地查词可用 · AI 待配置\n先查单词；配置模型后，再解锁 AI 助学、句子翻译和图片识别。"
        )
        self.configure_ai_button.setVisible(not ready)
        self.auto_ai_checkbox.setEnabled(ready)
        self.auto_ai_checkbox.setToolTip(
            "本地词典先查询，停止输入后再请求 AI；关闭后仍可手动查询。" if ready else
            "配置并选择可用的 AI 模型后可开启；当前仍可本地查词。"
        )
        if not ready:
            if hasattr(self, "ai_timer"):
                self.ai_timer.stop()
            if not self._busy:
                self.status.setText("本地查词可用 · AI 待配置")
        elif self.status.text() == "本地查词可用 · AI 待配置":
            self.status.setText("本地查词可用 · AI 已就绪")
        if self.current_kind == QueryKind.WORD and not self.word_view.note.plain_explanation:
            self.word_view.ai_state.setText(
                "点击“查询单词”获取 AI 补充。" if ready else
                "本地查词可用；配置 AI 模型后，可补充语境、搭配和例句。"
            )

    def _save_details_preference(self, expanded: bool) -> None:
        self.settings.set("learning_details_expanded", expanded)
        self.settings.save()

    def _model_changed(self, index: int) -> None:
        identifier = self.model_combo.itemData(index)
        if identifier:
            self.auto_timer.stop()
            self.ai_timer.stop()
            self.controller.cancel()
            self._last_ai_text = ""
            self.settings.select_model(str(identifier))
            self._refresh_ai_guidance()

    def open_model_settings(self) -> None:
        self.open_settings(model_page=True)

    def open_settings(self, *, model_page: bool = False) -> None:
        dialog = SettingsDialog(self.settings, self, autostart=self.autostart)
        if model_page:
            dialog.navigation.setCurrentRow(1)
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
