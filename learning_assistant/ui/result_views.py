"""Structured result widgets; no Markdown parsing is required."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from learning_assistant.domain.models import AiStudyNote, DictionaryEntry, SentenceResult


def text_label(text: str = "", object_name: str = "", selectable: bool = True) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if object_name:
        label.setObjectName(object_name)
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    return label


class Section(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)
        self.title = text_label(title, "section", selectable=False)
        self.value = text_label()
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        self.hide()

    def set_value(self, value: str) -> None:
        self.value.setText(value)
        self.setVisible(bool(value.strip()))


class WordResultView(QFrame):
    speak_requested = Signal(str)
    copy_requested = Signal(str)
    favorite_requested = Signal()
    study_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.entry: DictionaryEntry | None = None
        self.note = AiStudyNote()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(1)
        self.word = text_label("", "word")
        self.phonetic = text_label("", "phonetic")
        identity.addWidget(self.word)
        identity.addWidget(self.phonetic)
        header.addLayout(identity, 1)

        self.speak_button = QPushButton("朗读")
        self.speak_button.setObjectName("secondary")
        self.speak_button.clicked.connect(lambda: self.speak_requested.emit(self.word.text()))
        self.copy_button = QPushButton("复制")
        self.copy_button.setObjectName("secondary")
        self.copy_button.clicked.connect(lambda: self.copy_requested.emit(self.plain_text()))
        self.favorite_button = QPushButton("收藏")
        self.favorite_button.setObjectName("ghost")
        self.favorite_button.clicked.connect(self.favorite_requested)
        self.study_button = QPushButton("加入学习")
        self.study_button.setObjectName("primary")
        self.study_button.clicked.connect(self.study_requested)
        header.addWidget(self.speak_button, 0, Qt.AlignTop)
        header.addWidget(self.copy_button, 0, Qt.AlignTop)
        header.addWidget(self.favorite_button, 0, Qt.AlignTop)
        header.addWidget(self.study_button, 0, Qt.AlignTop)
        layout.addLayout(header)

        self.pos = text_label("", "muted")
        self.pos.hide()
        self.meanings = text_label()
        layout.addWidget(self.pos)
        layout.addWidget(self.meanings)

        self.ai_state = text_label("AI 助学内容生成中…", "muted", selectable=False)
        layout.addWidget(self.ai_state)

        self.plain = Section("通俗解释")
        self.context = Section("当前语境")
        self.synonyms = Section("近义词")
        self.collocations = Section("常用搭配")
        self.mistake = Section("易错提醒")
        self.memory = Section("记忆提示")
        self.examples = Section("例句")
        for section in (
            self.plain, self.context, self.synonyms, self.collocations,
            self.mistake, self.memory, self.examples,
        ):
            layout.addWidget(section)
        self.example_speak_button = QPushButton("朗读例句")
        self.example_speak_button.setObjectName("secondary")
        self.example_speak_button.clicked.connect(self._speak_examples)
        self.example_speak_button.hide()
        layout.addWidget(self.example_speak_button, 0, Qt.AlignLeft)
        layout.addStretch(1)

    def show_query(self, word: str) -> None:
        self.entry = None
        self.note = AiStudyNote()
        self.word.setText(word)
        self.phonetic.clear()
        self.pos.hide()
        self.meanings.setText("本地词典未找到，正在请 AI 辅助解释…")
        self.ai_state.show()
        self.example_speak_button.hide()
        for section in (
            self.plain, self.context, self.synonyms, self.collocations,
            self.mistake, self.memory, self.examples,
        ):
            section.hide()

    def show_entry(self, entry: DictionaryEntry) -> None:
        self.entry = entry
        self.word.setText(entry.display_word)
        self.phonetic.setText(f"/{entry.phonetic}/" if entry.phonetic else "")
        pos = " · ".join(entry.parts_of_speech)
        self.pos.setText(pos)
        self.pos.setVisible(bool(pos))
        lines = entry.translations or entry.definitions
        self.meanings.setText("\n".join(f"• {line}" for line in lines[:8]))
        self.ai_state.setText("AI 助学内容生成中…")
        self.ai_state.show()

    def show_note(self, note: AiStudyNote) -> None:
        self.note = note
        self.ai_state.hide()
        self.plain.set_value(note.plain_explanation)
        self.context.set_value(note.sense_in_context)
        self.synonyms.set_value(" · ".join(note.synonyms))
        self.collocations.set_value(" · ".join(note.collocations))
        self.mistake.set_value(note.common_mistake)
        self.memory.set_value(note.memory_tip)
        examples = []
        for index, item in enumerate(note.examples, 1):
            sentence = item.get("sentence", "")
            translation = item.get("translation", "")
            examples.append(f"{index}. {sentence}" + (f"\n   {translation}" if translation else ""))
        self.examples.set_value("\n\n".join(examples))
        self.example_speak_button.setVisible(bool(examples))

    def _speak_examples(self) -> None:
        sentences = [
            item.get("sentence", "").strip()
            for item in self.note.examples
            if item.get("sentence", "").strip()
        ]
        if sentences:
            self.speak_requested.emit(". ".join(sentences))

    def show_ai_error(self, message: str) -> None:
        self.ai_state.setText(f"AI 补充暂不可用：{message}")
        self.ai_state.show()

    def set_favorite(self, active: bool) -> None:
        self.favorite_button.setText("已收藏" if active else "收藏")

    def set_study(self, active: bool) -> None:
        self.study_button.setText("已加入" if active else "加入学习")
        self.study_button.setObjectName("secondary" if active else "primary")
        self.study_button.style().unpolish(self.study_button)
        self.study_button.style().polish(self.study_button)

    def plain_text(self) -> str:
        lines = [self.word.text()]
        if self.phonetic.text():
            lines.append(self.phonetic.text())
        if self.meanings.text():
            lines.append(self.meanings.text().replace("• ", ""))
        for section in (
            self.plain, self.context, self.synonyms, self.collocations,
            self.mistake, self.memory, self.examples,
        ):
            if section.isVisible() and section.value.text():
                lines.extend([section.title.text(), section.value.text()])
        return "\n".join(lines)


class SentenceResultView(QFrame):
    speak_requested = Signal(str)
    copy_requested = Signal(str)
    favorite_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.source_text = ""
        self.result = SentenceResult()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = text_label("自然译文", "section", selectable=False)
        header.addWidget(title)
        header.addStretch(1)
        self.speak_button = QPushButton("朗读原文")
        self.speak_button.setObjectName("secondary")
        self.speak_button.clicked.connect(lambda: self.speak_requested.emit(self.source_text))
        self.copy_button = QPushButton("复制")
        self.copy_button.setObjectName("secondary")
        self.copy_button.clicked.connect(lambda: self.copy_requested.emit(self.plain_text()))
        self.favorite_button = QPushButton("收藏")
        self.favorite_button.setObjectName("ghost")
        self.favorite_button.clicked.connect(self.favorite_requested)
        header.addWidget(self.speak_button)
        header.addWidget(self.copy_button)
        header.addWidget(self.favorite_button)
        layout.addLayout(header)
        self.translation = text_label()
        self.translation.setStyleSheet("font-size: 18px; line-height: 1.55;")
        layout.addWidget(self.translation)
        self.phrases = Section("关键表达")
        self.tip = Section("学习提示")
        layout.addWidget(self.phrases)
        layout.addWidget(self.tip)
        layout.addStretch(1)

    def set_source(self, text: str) -> None:
        self.source_text = text

    def show_result(self, result: SentenceResult) -> None:
        self.result = result
        self.translation.setText(result.translation)
        phrases = [
            f"{item.get('phrase', '')} — {item.get('meaning', '')}".rstrip(" —")
            for item in result.key_phrases
        ]
        self.phrases.set_value("\n".join(phrases))
        self.tip.set_value(result.learning_tip)

    def set_favorite(self, active: bool) -> None:
        self.favorite_button.setText("已收藏" if active else "收藏")

    def plain_text(self) -> str:
        lines = [self.translation.text()]
        if self.phrases.isVisible():
            lines.extend([self.phrases.title.text(), self.phrases.value.text()])
        if self.tip.isVisible():
            lines.extend([self.tip.title.text(), self.tip.value.text()])
        return "\n".join(lines)
