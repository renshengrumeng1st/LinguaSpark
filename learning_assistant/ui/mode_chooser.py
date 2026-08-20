"""Small startup chooser for LinguaSpark's focused work modes."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ModeChooser(QDialog):
    compact_requested = Signal()
    pdf_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LinguaSpark · 选择学习方式")
        self.setModal(False)
        self.setFixedSize(620, 310)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 26)
        root.setSpacing(16)

        title = QLabel("今天想怎么学？")
        title.setObjectName("chooserTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("选择后仍可从托盘或模式按钮随时切换")
        subtitle.setObjectName("chooserSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        root.addWidget(subtitle)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.compact_button = self._mode_card(
            "便捷模式", "查单词、翻译句子与图片\n适合随手查询"
        )
        self.pdf_button = self._mode_card(
            "PDF 阅读模式", "连续阅读、划线翻译与词组分析\n适合精读文献"
        )
        self.compact_button.clicked.connect(self.compact_requested)
        self.pdf_button.clicked.connect(self.pdf_requested)
        cards.addWidget(self.compact_button)
        cards.addWidget(self.pdf_button)
        root.addLayout(cards, 1)

        self.setStyleSheet(
            """
            QDialog { background: #f5f7f4; }
            QLabel#chooserTitle { color: #17201b; font-size: 24px; font-weight: 700; }
            QLabel#chooserSubtitle { color: #6b7280; font-size: 13px; }
            QPushButton#modeCard {
                background: white;
                color: #26332b;
                border: 1px solid #d8e2d8;
                border-radius: 14px;
                padding: 20px 16px;
                font-size: 16px;
                font-weight: 600;
                text-align: center;
            }
            QPushButton#modeCard:hover { background: #eaf4e2; border-color: #95b995; }
            QPushButton#modeCard:pressed { background: #dcebd4; }
            """
        )

    @staticmethod
    def _mode_card(title: str, description: str) -> QPushButton:
        button = QPushButton(f"{title}\n\n{description}")
        button.setObjectName("modeCard")
        button.setMinimumHeight(140)
        return button

    def show_front(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
