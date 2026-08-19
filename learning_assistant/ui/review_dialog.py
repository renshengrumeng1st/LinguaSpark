"""A small, practical review loop for words added to learning."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import LearningItem, ReviewRating
from learning_assistant.services.speech import SpeechProvider
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.result_views import text_label


class ReviewDialog(QDialog):
    queue_changed = Signal()

    def __init__(
        self,
        repository: LearningRepository,
        speech: SpeechProvider,
        settings: SettingsStore,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.speech = speech
        self.settings = settings
        self.items: list[LearningItem] = []
        self.current: LearningItem | None = None
        self._answer_visible = False
        self.setWindowTitle("今日复习 · LinguaSpark")
        self.resize(520, 430)
        self.setMinimumSize(460, 360)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(text_label("今日复习", "title", selectable=False))
        header.addStretch(1)
        self.progress = text_label("", "muted", selectable=False)
        header.addWidget(self.progress)
        root.addLayout(header)

        self.card = QFrame()
        self.card.setObjectName("card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(12)
        self.mode = text_label("", "muted", selectable=False)
        self.prompt = text_label("", "word")
        self.prompt.setAlignment(Qt.AlignCenter)
        self.hint = text_label("", "muted", selectable=False)
        self.hint.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.mode)
        card_layout.addStretch(1)
        card_layout.addWidget(self.prompt)
        card_layout.addWidget(self.hint)
        card_layout.addStretch(1)
        self.answer = text_label()
        self.answer.setObjectName("section")
        self.answer.hide()
        card_layout.addWidget(self.answer)
        root.addWidget(self.card, 1)

        self.reveal_button = QPushButton("显示答案")
        self.reveal_button.setObjectName("primary")
        self.reveal_button.clicked.connect(self._reveal)
        root.addWidget(self.reveal_button)

        self.rating_row = QWidget()
        ratings = QHBoxLayout(self.rating_row)
        ratings.setContentsMargins(0, 0, 0, 0)
        ratings.setSpacing(8)
        speak = QPushButton("朗读")
        speak.setObjectName("secondary")
        speak.clicked.connect(self._speak)
        again = QPushButton("不记得 · 10 分钟")
        hard = QPushButton("模糊 · 1 天+")
        good = QPushButton("记得 · 3 天+")
        again.setObjectName("ghost")
        hard.setObjectName("secondary")
        good.setObjectName("primary")
        again.clicked.connect(lambda: self._rate(ReviewRating.AGAIN))
        hard.clicked.connect(lambda: self._rate(ReviewRating.HARD))
        good.clicked.connect(lambda: self._rate(ReviewRating.GOOD))
        ratings.addWidget(speak)
        ratings.addStretch(1)
        ratings.addWidget(again)
        ratings.addWidget(hard)
        ratings.addWidget(good)
        self.rating_row.hide()
        root.addWidget(self.rating_row)

    def reload(self) -> None:
        self.items = self.repository.due_learning_items(limit=100)
        self._show_next()

    def _show_next(self) -> None:
        self.current = self.items.pop(0) if self.items else None
        self._answer_visible = False
        self.answer.hide()
        self.rating_row.hide()
        self.reveal_button.show()
        if self.current is None:
            self.progress.setText("0 待复习")
            self.mode.setText("已完成")
            self.prompt.setText("今天的复习完成了")
            self.hint.setText("之后遇到值得记住的单词，点击“加入学习”即可。")
            self.answer.clear()
            self.reveal_button.hide()
            return
        self.progress.setText(f"还剩 {len(self.items) + 1}")
        front, answer, is_cloze = self._card_content(self.current)
        self.mode.setText("例句挖空" if is_cloze else "回忆词义")
        self.prompt.setText(front)
        self.hint.setText("先在心里回答，再显示答案")
        self.answer.setText(answer)

    @staticmethod
    def _card_content(item: LearningItem) -> tuple[str, str, bool]:
        dictionary = item.payload.get("dictionary", {})
        note = item.payload.get("ai_note", {})
        translations = dictionary.get("translations") or dictionary.get("definitions") or []
        meanings = "\n".join(f"• {line}" for line in translations[:6])
        explanation = str(note.get("plain_explanation", "")).strip()
        examples = note.get("examples", []) if isinstance(note.get("examples", []), list) else []
        example = examples[0] if examples and isinstance(examples[0], dict) else {}
        sentence = str(example.get("sentence", "")).strip()
        translation = str(example.get("translation", "")).strip()
        # Alternate card types across successful reviews; a new card starts with meaning recall.
        if item.streak % 2 == 1 and sentence:
            pattern = re.compile(rf"\b{re.escape(item.source_text)}\b", re.IGNORECASE)
            cloze = pattern.sub("____", sentence)
            if cloze != sentence:
                answer_parts = [item.source_text]
                if meanings:
                    answer_parts.append(meanings)
                if translation:
                    answer_parts.append(translation)
                return cloze, "\n\n".join(answer_parts), True
        answer_parts = [meanings or "暂无本地释义"]
        if explanation:
            answer_parts.append(explanation)
        if sentence:
            answer_parts.append(sentence + (f"\n{translation}" if translation else ""))
        return item.source_text, "\n\n".join(answer_parts), False

    def _reveal(self) -> None:
        if not self.current:
            return
        self._answer_visible = True
        self.answer.show()
        self.reveal_button.hide()
        self.rating_row.show()

    def _rate(self, rating: ReviewRating) -> None:
        if not self.current or not self._answer_visible:
            return
        self.repository.review_item(self.current.item_key, rating)
        self.queue_changed.emit()
        self._show_next()

    def _speak(self) -> None:
        if not self.current:
            return
        locale = str(self.settings.get("tts", {}).get("voice_locale", "en-US"))
        self.speech.speak(self.current.source_text, locale)

