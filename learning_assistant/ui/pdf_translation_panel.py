"""Translation-only output, independent from PDF question history."""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from learning_assistant.ui.pdf_question_panel import PdfAnswerBrowser
from learning_assistant.ui.pdf_math import PdfMathRenderer


class PdfTranslationPanel(QWidget):
    output_reset = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text, self._error = "", ""
        self._pending = False
        self._disposed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("译文"))
        heading.addStretch(1)
        self.clear_button = QPushButton("清空译文")
        heading.addWidget(self.clear_button)
        root.addLayout(heading)
        self.output_frame = QFrame()
        self.output_frame.setObjectName("pdfOutput")
        self.output_layout = QVBoxLayout(self.output_frame)
        self.output_layout.setContentsMargins(8, 6, 8, 6)
        self.answer_browser = PdfAnswerBrowser(lambda _: "")
        self.answer_browser.setOpenLinks(False)
        self.answer_browser.setStyleSheet("color:#1f2937; background:transparent; border:none; padding:4px;")
        self.output_layout.addWidget(self.answer_browser, 1)
        root.addWidget(self.output_frame, 1)
        self.status = QLabel()
        self.status.setObjectName("pdfStatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        root.addWidget(self.status)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._render)
        self.math_renderer = PdfMathRenderer(self.answer_browser, self)
        self.math_renderer.ready.connect(self._schedule)
        self.clear_button.clicked.connect(self._clear)
        self._render()

    def _schedule(self):
        if not self._disposed and not self._timer.isActive():
            self._timer.start()

    def start_translation(self):
        self._text, self._error, self._pending = "", "", True
        self._render()

    def append_translation(self, text):
        self._pending = False
        self._text += text
        self._schedule()

    def finish_translation(self, text):
        self._text, self._error, self._pending = text, "", False
        self._render()

    def fail_translation(self, message):
        self._error, self._pending = message, False
        self._render()

    def clear_translation(self):
        self._text, self._error, self._pending = "", "", False
        self._timer.stop()
        self._render()

    def _clear(self):
        self.clear_translation()
        self.output_reset.emit()

    def _render(self):
        from html import escape
        content = self.math_renderer.format(self._text) or ("翻译中…" if self._pending else "")
        if self._error:
            content += f'<p style="color:#9b3b35">{escape(self._error)}</p>'
        self.answer_browser.setHtml(content)
        self.clear_button.setEnabled(bool(self._text or self._error or self._pending))

    def dispose(self):
        self._disposed = True
        self._timer.stop()
        self.math_renderer.dispose()
