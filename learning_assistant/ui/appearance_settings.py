"""Live style picker with code-drawn previews, including a small star mascot."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QLabel, QRadioButton, QVBoxLayout, QWidget,
)

from learning_assistant.core.settings import SettingsStore
from learning_assistant.ui.theme import THEMES, apply_app_theme
from learning_assistant.ui.theme_illustration import draw_illustration


class StylePreview(QWidget):
    def __init__(self, theme_id: str, parent=None):
        super().__init__(parent)
        self.theme_id = theme_id
        self.setFixedHeight(94)
        self.setMinimumWidth(180)

    def paintEvent(self, event) -> None:
        theme = THEMES[self.theme_id]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        def box(x, y, width, height, color, radius=5):
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, y, width, height), radius, radius)

        width = self.width()
        box(0, 0, width, 94, theme.background, 9)
        box(9, 9, 38, 76, theme.sidebar, 6)
        box(19, 19, 18, 18, theme.accent, 6)
        for y in (47, 58, 69):
            box(18, y, 20, 4, theme.line, 2)
        box(59, 17, 69, 7, theme.text, 3)
        box(59, 31, 104, 4, theme.muted, 2)
        box(59, 45, width - 70, 38, theme.surface, 6)
        box(69, 55, 65, 5, theme.line, 2)
        box(69, 66, 96, 4, theme.soft, 2)
        box(width - 58, 55, 37, 17, theme.accent, 5)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        draw_illustration(p, QRectF(width - 99, 0, 96, 91), self.theme_id)
        p.end()


class AppearanceSettingsPage(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.theme_buttons: dict[str, QRadioButton] = {}
        self._cards: dict[str, QFrame] = {}
        self._group = QButtonGroup(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        hint = QLabel("给学习空间换一种心情。选择后立即应用，并自动记住你的偏好。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)
        grid = QGridLayout()
        grid.setSpacing(16)
        selected = str(settings.get("appearance", {}).get("theme", "sakura"))
        for index, (theme_id, theme) in enumerate(THEMES.items()):
            card = QFrame()
            card.setObjectName("themeCard")
            card.setProperty("chosen", theme_id == selected)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(15, 15, 15, 15)
            layout.setSpacing(9)
            preview = StylePreview(theme_id)
            layout.addWidget(preview)
            button = QRadioButton(theme.name)
            button.setChecked(theme_id == selected)
            button.clicked.connect(lambda _checked, key=theme_id: self._choose(key))
            preview.mousePressEvent = lambda _event, target=button: target.click()
            self._group.addButton(button)
            self.theme_buttons[theme_id] = button
            self._cards[theme_id] = card
            layout.addWidget(button)
            description = QLabel(theme.subtitle)
            description.setObjectName("muted")
            layout.addWidget(description)
            grid.addWidget(card, index // 2, index % 2)
        root.addLayout(grid)
        note = QLabel("界面风格适用于便捷模式、设置、划词弹窗和阅读器工具栏。PDF 纸张背景仍可在阅读器中独立选择。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        character_note = QLabel("角色主题使用新绘制的 Q 版插画。装饰仅出现在主题预览、空白页和复习完成页，正文保持清晰。")
        character_note.setWordWrap(True)
        character_note.setObjectName("muted")
        root.addWidget(character_note)
        root.addStretch(1)

    def _choose(self, theme_id: str) -> None:
        self.settings.set("appearance", {"theme": theme_id})
        self.settings.save()
        apply_app_theme(theme_id)
        for key, card in self._cards.items():
            card.setProperty("chosen", key == theme_id)
            card.style().unpolish(card)
            card.style().polish(card)
        self.settings_changed.emit()
