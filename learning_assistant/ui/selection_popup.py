"""Small near-cursor result surface for global selection lookup."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from learning_assistant.controller import LearningController
from learning_assistant.domain.models import AiStudyNote, DictionaryEntry, QueryKind, QueryRequest, SentenceResult


class SelectionPopup(QWidget):
    open_main_requested = Signal(str)
    speak_requested = Signal(str)

    def __init__(self, controller: LearningController):
        super().__init__(
            None,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.controller = controller
        self.source_text = ""
        self.current_kind: QueryKind | None = None
        self._request_text = ""
        self._accepting_result = False
        self._anchor = QPoint()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(430)
        self.setMaximumHeight(410)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        self.card = QFrame()
        self.card.setObjectName("card")
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 15, 18, 14)
        layout.setSpacing(8)
        title_row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("title")
        title_row.addWidget(self.title, 1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("ghost")
        close_button.clicked.connect(self.hide)
        title_row.addWidget(close_button)
        layout.addLayout(title_row)
        self.phonetic = QLabel()
        self.phonetic.setObjectName("phonetic")
        layout.addWidget(self.phonetic)
        self.content = QLabel()
        self.content.setWordWrap(True)
        self.content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.content)
        self.ai_note = QLabel()
        self.ai_note.setWordWrap(True)
        self.ai_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ai_note.setObjectName("muted")
        layout.addWidget(self.ai_note)
        actions = QHBoxLayout()
        actions.addStretch(1)
        speak = QPushButton("朗读")
        speak.setObjectName("secondary")
        speak.clicked.connect(lambda: self.speak_requested.emit(self.source_text))
        copy = QPushButton("复制")
        copy.setObjectName("secondary")
        copy.clicked.connect(self._copy)
        open_main = QPushButton("展开学习")
        open_main.setObjectName("primary")
        open_main.clicked.connect(lambda: self.open_main_requested.emit(self.source_text))
        actions.addWidget(speak)
        actions.addWidget(copy)
        actions.addWidget(open_main)
        layout.addLayout(actions)
        outer.addWidget(self.card)

        controller.query_started.connect(self._started)
        controller.word_ready.connect(self._word)
        controller.ai_note_ready.connect(self._note)
        controller.sentence_ready.connect(self._sentence)
        controller.query_failed.connect(self._error)

    def show_query(self, text: str, anchor: QPoint | None = None) -> None:
        self.source_text = text
        self._request_text = text.strip()
        self._accepting_result = False
        self._anchor = QPoint(anchor) if anchor is not None else QPoint()
        self.title.setText(text[:70] + ("…" if len(text) > 70 else ""))
        self.phonetic.clear()
        self.content.setText("正在查询…")
        self.ai_note.clear()
        self.adjustSize()
        self._fit_to_screen()
        self.show()
        self.raise_()

    def _fit_to_screen(self) -> None:
        anchor = self._anchor
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(anchor.x() + 14, area.right() - self.width())
        y = min(anchor.y() + 18, area.bottom() - max(260, self.height()))
        x = max(area.left(), x)
        y = max(area.top(), y)
        self.move(x, y)

    def _started(self, request: QueryRequest) -> None:
        if not self.isVisible():
            return
        self._accepting_result = request.text.strip() == self._request_text
        if not self._accepting_result:
            return
        self.current_kind = request.kind
        self.source_text = request.text

    def _word(self, entry: DictionaryEntry, elapsed_ms: int) -> None:
        if not self.isVisible() or not self._accepting_result:
            return
        self.title.setText(entry.display_word)
        self.phonetic.setText(f"/{entry.phonetic}/" if entry.phonetic else "")
        self.content.setText("\n".join(entry.translations[:5] or entry.definitions[:5]))
        self.ai_note.setText(f"本地词典 {elapsed_ms} ms · AI 正在补充…")
        self.adjustSize()
        self._fit_to_screen()

    def _note(self, note: AiStudyNote, cache_hit: bool) -> None:
        if not self.isVisible() or not self._accepting_result:
            return
        useful = note.sense_in_context or note.plain_explanation or note.memory_tip
        self.ai_note.setText(useful)
        self.adjustSize()
        self._fit_to_screen()

    def _sentence(self, result: SentenceResult, cache_hit: bool) -> None:
        if not self.isVisible() or not self._accepting_result:
            return
        self.content.setText(result.translation)
        self.ai_note.setText(result.learning_tip)
        self.adjustSize()
        self._fit_to_screen()

    def _error(self, message: str) -> None:
        if self.isVisible() and self._accepting_result:
            self.ai_note.setText(message)
            self.adjustSize()
            self._fit_to_screen()

    def _copy(self) -> None:
        value = self.content.text()
        if self.ai_note.text():
            value += "\n" + self.ai_note.text()
        QApplication.clipboard().setText(value)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
