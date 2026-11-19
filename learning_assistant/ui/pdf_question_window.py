"""Nonmodal, per-document PDF question composer and conversation window."""

from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel


class _DragBar(QWidget):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class PdfQuestionWindow(QDialog):
    def __init__(self, settings, parent, translate):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("pdfQuestionWindow")
        self.setWindowTitle("PDF 问答")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(420, 160)
        self._positioned = False
        self._expanded = False
        self._disposed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("pdfQuestionCard")
        card = QVBoxLayout(self.card)
        card.setContentsMargins(18, 10, 18, 14)
        card.setSpacing(4)
        drag = _DragBar()
        header = QHBoxLayout(drag)
        header.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("PDF 问答")
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self.title, 1)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setToolTip("收起（Esc）")
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        card.addWidget(drag)
        self.panel = PdfQuestionPanel(settings)
        self.panel.question_input.setPlaceholderText("向当前 PDF 提问…")
        self.panel.question_input.setMinimumHeight(66)
        self.panel.question_input.setMaximumHeight(100)
        self.panel.send_button.setText("↑")
        self.panel.send_button.setObjectName("pdfQuestionSend")
        self.panel.send_button.setFixedSize(36, 36)
        card.addWidget(self.panel, 1)
        root.addWidget(self.card)
        self._toggle_shortcut = QShortcut(QKeySequence(), self)
        self._toggle_shortcut.setAutoRepeat(False)
        self._toggle_shortcut.activated.connect(self.hide)
        self._translate_shortcut = QShortcut(QKeySequence(), self)
        self._translate_shortcut.setAutoRepeat(False)
        self._translate_shortcut.activated.connect(translate)
        self.panel.controller.started.connect(lambda *_: self._set_expanded(True))
        self.panel.output_reset.connect(lambda: self._set_expanded(False))
        self.panel.attachment_changed.connect(lambda _: self._set_expanded(self._expanded, force=True))
        self.set_reading_color("#EAF4E2")
        self._set_expanded(False)
        self.hide()

    def set_reading_color(self, paper):
        self.panel.answer_browser.set_reading_color(paper)
        self.setStyleSheet(f"""
            QFrame#pdfQuestionCard {{background:{paper};border:1px solid #b5bfa8;border-radius:20px;}}
            QLabel {{color:#1f2937;background:transparent;}}
            QPlainTextEdit#pdfQuestionInput {{color:#1f2937;background:transparent;border:none;padding:6px;font-size:18px;}}
            QFrame#pdfOutput {{background:transparent;border:none;}}
            QPushButton#pdfQuestionSend {{background:#66864c;color:white;border:none;border-radius:18px;padding:0;font-size:24px;}}
            QPushButton#pdfQuestionSend:disabled {{background:#dfe5d9;color:#a8b1a0;}}
            QToolButton {{color:#687469;background:transparent;border:none;padding:3px;font-size:20px;}}
        """)

    def set_bindings(self, question, translation):
        self._toggle_shortcut.setKey(QKeySequence(question.replace("Win+", "Meta+")))
        self._translate_shortcut.setKey(QKeySequence(translation.replace("Win+", "Meta+")))

    def set_document_title(self, path):
        name = Path(path).name
        self.title.setText("PDF 问答" + (" · " + name[:48] if name else ""))
        self.title.setToolTip(name)

    def _set_expanded(self, expanded, *, force=False):
        changed = expanded != self._expanded
        self._expanded = expanded
        self.panel.heading_widget.setVisible(expanded)
        self.panel.output_frame.setVisible(expanded)
        if self._positioned and not changed and not force:
            return
        available = self.screen().availableGeometry()
        old_bottom = self.geometry().bottom()
        height = (560 if expanded else 180) + (90 if self.panel.image_bytes else 0)
        self.resize(self.width() if self._positioned else min(660, available.width()-40),
                    min(height, available.height()-40))
        if self._positioned:
            self.move(self.x(), max(available.top()+12, old_bottom-self.height()+1))

    def show_front(self):
        if self._disposed:
            return
        self._set_expanded(bool(self.panel._entries))
        available = self.screen().availableGeometry()
        if not self._positioned:
            owner = self.parentWidget().pdf_view
            bottom = owner.mapToGlobal(QPoint(owner.width()//2, owner.height()-24))
            self.move(max(available.left()+12, min(bottom.x()-self.width()//2, available.right()-self.width()-12)),
                      max(available.top()+12, min(bottom.y()-self.height(), available.bottom()-self.height()-12)))
            self._positioned = True
        self.show()
        self.raise_()
        self.activateWindow()
        self.panel.question_input.setFocus()

    def reject(self):
        self.hide()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def dispose(self):
        self._disposed = True
        self.hide()
        self.panel.dispose()
