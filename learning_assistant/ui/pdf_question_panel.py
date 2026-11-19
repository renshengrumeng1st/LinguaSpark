"""Question input and safely rendered conversation for the PDF question window."""

from html import escape
import re

from PySide6.QtCore import QEvent, QFileInfo, QMimeData, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QKeySequence, QPalette, QPixmap, QShortcut, QTextDocument
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QToolButton, QToolTip, QVBoxLayout, QWidget

from learning_assistant.pdf_question_controller import PdfQuestionController
from learning_assistant.services.pdf_question_images import image_part
from learning_assistant.ui.input_edit import InputEdit


class PdfAnswerBrowser(QTextBrowser):
    """Use a bounded, paper-colored quote preview instead of native tooltips."""

    def __init__(self, quote_for_url, parent=None):
        super().__init__(parent)
        self._quote_for_url = quote_for_url
        self._tip_anchor = ""
        self._citation_tip = QFrame(self, Qt.WindowType.ToolTip)
        self._citation_tip.setObjectName("pdfCitationTooltip")
        self._citation_tip.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._citation_tip.setAutoFillBackground(True)
        self._citation_tip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self._citation_tip)
        layout.setContentsMargins(10, 8, 10, 8)
        self._quote_label = QLabel()
        self._quote_label.setTextFormat(Qt.TextFormat.PlainText)
        self._quote_label.setWordWrap(True)
        layout.addWidget(self._quote_label)
        self.set_reading_color("#EAF4E2")

    def set_reading_color(self, paper):
        palette = self._citation_tip.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(paper))
        self._citation_tip.setPalette(palette)
        self._citation_tip.setStyleSheet(
            f"QFrame#pdfCitationTooltip {{ background-color: {paper}; border: 1px solid #9ca88c; border-radius: 6px; }}"
            "QLabel { color: #1f2937; background: transparent; border: none; }"
        )

    def setHtml(self, text):
        self._citation_tip.hide()
        super().setHtml(text)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
            anchor = self.anchorAt(event.pos())
            quote = self._quote_for_url(anchor)
            if quote:
                self._tip_anchor = anchor
                tip = self._citation_tip
                available = self.screen().availableGeometry()
                width = min(420, available.width() - 20)
                tip.ensurePolished()
                frame = tip.frameWidth() * 2
                text_width = width - 20 - frame
                self._quote_label.setFixedWidth(text_width)
                self._quote_label.setText(quote)
                height = min(available.height() - 20, self._quote_label.heightForWidth(text_width) + 16 + frame)
                tip.setFixedSize(width, height)
                position = event.globalPos() + QPoint(12, 18)
                position.setX(max(available.left() + 4, min(position.x(), available.right() - width - 4)))
                position.setY(max(available.top() + 4, min(position.y(), available.bottom() - height - 4)))
                tip.move(position)
                tip.show()
            else:
                self._citation_tip.hide()
            event.accept()
            return True
        if event.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.Hide):
            self._citation_tip.hide()
        if event.type() == QEvent.Type.MouseMove and self.anchorAt(event.pos()) != self._tip_anchor:
            self._citation_tip.hide()
        return super().viewportEvent(event)


class PdfQuestionPanel(QWidget):
    page_requested = Signal(int)
    citation_requested = Signal(int, str)
    output_reset = Signal()
    attachment_changed = Signal(bool)

    def __init__(self, settings, parent=None, *, controller=None):
        super().__init__(parent)
        self.controller = controller or PdfQuestionController(settings, self)
        self._selection = None
        self._entries = []
        self._active_entry = None
        self._status_error = False
        self._pending_label = "回答中…"
        self._citations = []
        self.image_bytes = None
        self._image_thumbnail = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(6)
        self.heading_widget = QWidget()
        heading = QHBoxLayout(self.heading_widget)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.addWidget(QLabel("对话"))
        heading.addStretch(1)
        self.copy_button = QPushButton("复制")
        self.copy_button.setToolTip("复制最近一次回答")
        self.clear_button = QPushButton("清空对话")
        self.clear_button.setToolTip("清空本篇问答记录")
        heading.addWidget(self.copy_button)
        heading.addWidget(self.clear_button)
        root.addWidget(self.heading_widget)
        self.output_frame = QFrame()
        self.output_frame.setObjectName("pdfOutput")
        self.output_layout = QVBoxLayout(self.output_frame)
        self.output_layout.setContentsMargins(8, 6, 8, 6)
        self.answer_browser = PdfAnswerBrowser(self._citation_quote)
        self.answer_browser.setMinimumHeight(70)
        self.answer_browser.setFrameShape(QFrame.NoFrame)
        self.answer_browser.setOpenExternalLinks(False)
        self.answer_browser.setOpenLinks(False)
        self.answer_browser.setStyleSheet("color: #1f2937; background: transparent; border: none; padding: 4px;")
        self.answer_browser.anchorClicked.connect(self._open_page)
        self.output_layout.addWidget(self.answer_browser, 1)
        root.addWidget(self.output_frame, 1)
        self.image_row = QWidget()
        image_layout = QHBoxLayout(self.image_row)
        image_layout.setContentsMargins(6, 0, 6, 0)
        self.image_preview = QLabel()
        self.image_preview.setFixedSize(112, 72)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout.addWidget(self.image_preview)
        image_layout.addWidget(QLabel("已附截图"))
        image_layout.addStretch(1)
        self.remove_image_button = QToolButton()
        self.remove_image_button.setText("×")
        self.remove_image_button.setToolTip("移除截图")
        image_layout.addWidget(self.remove_image_button)
        self.image_row.hide()
        root.addWidget(self.image_row)
        self.question_input = InputEdit(max_image_pixels=40_000_000)
        self.question_input.setObjectName("pdfQuestionInput")
        self.question_input.setPlaceholderText("输入问题…")
        self.question_input.setToolTip("结合全文、划句和截图提问；Ctrl+V 粘贴截图，Ctrl+Enter 发送")
        self.question_input.setMinimumHeight(52)
        self.question_input.setMaximumHeight(76)
        root.addWidget(self.question_input)
        actions = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.setToolTip("发送（Ctrl+Enter）")
        self.send_button.setObjectName("primary")
        self.stop_button = QPushButton("停止")
        self.upload_image_button = QPushButton("上传截图")
        self.upload_image_button.setToolTip("选择一张截图；再次上传会替换当前截图")
        actions.addWidget(self.upload_image_button)
        actions.addStretch(1)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.send_button)
        root.addLayout(actions)
        self.status = QLabel()
        self.status.setObjectName("pdfStatus")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(42)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(50)
        self._render_timer.timeout.connect(self._render)
        from learning_assistant.ui.pdf_math import PdfMathRenderer
        self.math_renderer = PdfMathRenderer(self.answer_browser, self)
        self.math_renderer.ready.connect(self._math_ready)
        self._disposed = False
        self._send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.question_input)
        self._send_shortcut.setKeys([QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
        self._send_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._send_shortcut.activated.connect(self._send)
        self.question_input.textChanged.connect(self._buttons)
        self.question_input.submit_requested.connect(self._send)
        self.question_input.image_pasted.connect(self._set_image)
        self.question_input.image_rejected.connect(self._image_failed)
        self.upload_image_button.clicked.connect(self._upload_image)
        self.remove_image_button.clicked.connect(self._remove_image)
        self.send_button.clicked.connect(self._send)
        self.stop_button.clicked.connect(self.controller.cancel)
        self.clear_button.clicked.connect(self.controller.clear)
        self.copy_button.clicked.connect(self._copy)
        self.controller.started.connect(self._started)
        self.controller.partial.connect(self._partial)
        self.controller.completed.connect(self._completed)
        self.controller.failed.connect(self._failed)
        self.controller.state_changed.connect(self._state)
        self.controller.conversation_reset.connect(self._reset)
        self.set_selection(None)
        self._state("")
        self._render()

    def set_document(self, path, identity, page_count=0):
        self.set_selection(None)
        self.controller.set_document(path, identity, page_count)

    def set_selection(self, selection):
        self._selection = selection

    def _send(self):
        selection = self._selection
        self.controller.ask(self.question_input.toPlainText(), selection.text if selection else "",
                            selection.page_index if selection and selection.page_index >= 0 else None,
                            image_bytes=self.image_bytes)

    def _upload_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择截图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)")
        if path:
            if QFileInfo(path).size() > 32 * 1024 * 1024:
                self._image_failed("图片文件超过 32 MB，请裁剪后重试。")
                return
            if not QImageReader(path).canRead():
                self._image_failed("无法读取图片，请选择有效的截图文件。")
                return
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            self.question_input.insertFromMimeData(mime)
        self.question_input.setFocus()

    def _set_image(self, data):
        if self.controller.busy:
            return
        try:
            image_part(data)
        except ValueError as error:
            self._image_failed(str(error))
            return
        self.image_bytes = bytes(data)
        self._image_thumbnail = QImage.fromData(data).scaled(180, 110, Qt.AspectRatioMode.KeepAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation)
        image = QPixmap.fromImage(self._image_thumbnail)
        self.image_preview.setPixmap(image.scaled(self.image_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        self.image_row.show()
        self._status_error = False
        self.status.hide()
        self._buttons()
        self.attachment_changed.emit(True)

    def _remove_image(self):
        self.image_bytes = None
        self._image_thumbnail = None
        self.image_preview.clear()
        self.image_row.hide()
        self._buttons()
        self.attachment_changed.emit(False)

    def _image_failed(self, message):
        self._status_error = True
        self._state(message)

    def _started(self, question, selected_text):
        self._status_error = False
        self._entries.append({"question": question, "selection": selected_text, "answer": "", "error": "",
                              "image": self._image_thumbnail})
        self._active_entry = len(self._entries) - 1
        self._render()
        self._buttons()

    def _partial(self, text):
        if self._active_entry is not None:
            self._entries[self._active_entry]["answer"] += text
            if not self._render_timer.isActive():
                self._render_timer.start()

    def _completed(self, text):
        if self._active_entry is not None:
            self._entries[self._active_entry]["answer"] = text
        self._active_entry = None
        self._status_error = False
        self.question_input.clear()
        self._remove_image()
        self._render_timer.stop()
        self._render()
        self._buttons()

    def _failed(self, message):
        has_entry = self._active_entry is not None
        if self._active_entry is not None:
            self._entries[self._active_entry]["error"] = message
        self._active_entry = None
        self._status_error = not has_entry
        self._render_timer.stop()
        self._render()
        self._state(message)

    def _state(self, message):
        if self.controller.busy:
            self._pending_label = "读取全文…" if "读取" in message else "回答中…"
            if self._active_entry is not None and not self._entries[self._active_entry]["answer"]:
                self._render()
        self.status.setText(message)
        self.status.setToolTip(message)
        self.status.setVisible(self._status_error)
        self._buttons()

    def _buttons(self):
        self.question_input.setReadOnly(self.controller.busy)
        self.send_button.setEnabled(bool(self.controller.path)
                                   and bool(self.question_input.toPlainText().strip() or self.image_bytes)
                                   and not self.controller.busy)
        self.upload_image_button.setEnabled(not self.controller.busy)
        self.remove_image_button.setEnabled(not self.controller.busy)
        self.stop_button.setEnabled(self.controller.busy)
        self.stop_button.setVisible(self.controller.busy)
        self.clear_button.setEnabled(bool(self._entries) or self.controller.busy or self.image_bytes is not None)
        self.copy_button.setEnabled(bool(self.controller.history))

    def _reset(self):
        self._render_timer.stop()
        self._entries.clear()
        self._active_entry = None
        self._status_error = False
        self.question_input.clear()
        self._remove_image()
        self._render()
        self.output_reset.emit()

    def _answer_html(self, text):
        def reference(match):
            page = int(match.group(1))
            if 1 <= page <= self.controller.page_count:
                quote = (match.group(2) or "").strip()
                index = len(self._citations)
                self._citations.append((page - 1, quote))
                return f'<a href="pdf-citation:{index}">[第 {page} 页]</a>'
            return escape(match.group(0))
        pattern = r"\[第\s*([0-9]{1,6})\s*页(?:[｜|]\s*([^\]\r\n]{1,500}))?\]"
        references = [(match.start(), match.end(), lambda value=match: reference(value))
                      for match in re.finditer(pattern, text)]
        return self.math_renderer.format(text, references)

    def _math_ready(self):
        if not self._disposed and not self._render_timer.isActive():
            self._render_timer.start()

    def _render(self):
        bar = self.answer_browser.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 24
        position = bar.value()
        blocks = []
        self._citations = []
        for index, entry in enumerate(self._entries):
            blocks.append(f'<p><b>你</b><br>{escape(entry["question"]).replace(chr(10), "<br>")}</p>')
            if entry.get("image"):
                image = entry["image"]
                url = QUrl(f"pdf-question-image:{index}")
                self.answer_browser.document().addResource(QTextDocument.ResourceType.ImageResource, url, image)
                blocks.append(f'<p><img src="{url.toString()}" width="{image.width()}" height="{image.height()}" alt="已附截图"></p>')
            blocks.append(f'<p><b>回答</b></p>{self._answer_html(entry["answer"]) or (self._pending_label if not entry["error"] else "")}')
            if entry["error"]:
                blocks.append(f'<p style="color:#9b3b35">{escape(entry["error"])}</p>')
            blocks.append("<hr>")
        self.answer_browser.setHtml("".join(blocks))
        bar.setValue(bar.maximum() if follow else position)

    def _open_page(self, url):
        self.answer_browser._citation_tip.hide()
        if url.scheme() == "pdf-citation" and len(url.path()) <= 8 and url.path().isdigit():
            index = int(url.path())
            if index < len(self._citations):
                page, quote = self._citations[index]
                self.page_requested.emit(page)
                self.citation_requested.emit(page, quote)
            return
        if url.scheme() == "pdf-page" and len(url.path()) <= 6 and url.path().isdigit():
            page = int(url.path())
            if 1 <= page <= self.controller.page_count:
                self.page_requested.emit(page - 1)
                self.citation_requested.emit(page - 1, "")

    def _citation_quote(self, anchor):
        prefix = "pdf-citation:"
        value = anchor[len(prefix):] if anchor.startswith(prefix) else ""
        if value.isdigit() and len(value) <= 8 and int(value) < len(self._citations):
            return self._citations[int(value)][1]
        return ""

    def _copy(self):
        if self.controller.history:
            QApplication.clipboard().setText(self.controller.history[-1]["content"])

    def dispose(self):
        self._disposed = True
        self.answer_browser._citation_tip.hide()
        self._render_timer.stop()
        self.math_renderer.dispose()
        self.controller.dispose()
