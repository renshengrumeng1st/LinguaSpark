"""Independent question history and cancellation for one open PDF document."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from learning_assistant.services.pdf_document_text import PdfDocumentTextLoader
from learning_assistant.services.pdf_questions import QtPdfQuestionClient
from learning_assistant.services.pdf_text import document_key
from learning_assistant.services.pdf_question_images import DEFAULT_IMAGE_QUESTION, user_message


class PdfQuestionController(QObject):
    started = Signal(str, str)
    partial = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)
    conversation_reset = Signal()

    def __init__(self, settings, parent=None, *, client=None, loader=None):
        super().__init__(parent)
        self.settings = settings
        self.client = client or QtPdfQuestionClient(self)
        self.loader = loader or PdfDocumentTextLoader(self)
        self.history = []
        self.page_count = 0
        self.path = ""
        self._identity = ""
        self._pages = None
        self._request_id = None
        self._disposed = False
        self._question = ""
        self._focus = {"text": "", "page": None}
        self._answer = ""
        self._image_bytes = None
        self._request_user = None
        self._profile = None
        self._answer_style = ""
        self.busy = False
        self.client.partial.connect(self._partial)
        self.client.completed.connect(self._completed)
        self.client.failed.connect(self._failed)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._extraction_failed)

    def set_document(self, path: str, identity: str, page_count=0) -> None:
        if self._disposed:
            return
        self.clear()
        self.path, self._identity, self.page_count = path, identity, page_count
        self._pages = None
        self.state_changed.emit("全文文字＋划中句子＋问题；发送时交给当前模型。" if path else "请先打开 PDF。")

    def ask(self, question: str, selected_text="", selected_page=None, image_bytes=None) -> None:
        if self._disposed or self.busy:
            return
        try:
            if not self.path:
                raise ValueError("请先打开 PDF，再提问。")
            if document_key(Path(self.path)) != self._identity:
                raise ValueError("PDF 文件已变化，请重新打开后提问。")
            profile = self.settings.active_model()
            if not profile or not profile.enabled or not profile.api_key:
                raise ValueError("请先在设置中配置可用的 AI 模型。")
            question = question.strip() or (DEFAULT_IMAGE_QUESTION if image_bytes is not None else "")
            if not question or len(question) > 4000:
                raise ValueError("请输入不超过 4,000 字符的问题。")
            if len(selected_text) > 4000:
                raise ValueError("划中句子过长，请缩小选区后提问。")
            focus = {"text": selected_text, "page": selected_page + 1 if selected_page is not None else None}
            request_user = user_message(question, focus, image_bytes)
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self._question, self._answer, self._profile = question.strip(), "", profile
        self._answer_style = self.settings.get("pdf_question_answer_style", "")
        self._focus = focus
        self._image_bytes = bytes(image_bytes) if image_bytes is not None else None
        self._request_user = request_user
        self.busy = True
        self.started.emit(self._question, selected_text)
        self.state_changed.emit("正在读取 PDF 全文…" if self._pages is None else "正在回答…")
        if self._pages is None:
            if self._image_bytes is not None:
                self.loader.load(Path(self.path), allow_empty=True)
            else:
                self.loader.load(Path(self.path))
        else:
            self._send()

    def _loaded(self, pages) -> None:
        if self._disposed or not self.busy or self._request_id is not None:
            return
        self._pages = tuple(pages)
        self.page_count = len(pages)
        self._send()

    def _send(self) -> None:
        try:
            if document_key(Path(self.path)) != self._identity:
                raise ValueError("PDF 文件已变化，请重新打开后提问。")
            args = (self._profile, self._pages, self._question,
                    deepcopy(self.history), self.settings.languages(), dict(self._focus))
            if self._image_bytes is not None:
                args += (self._image_bytes,)
            self._request_id = self.client.start(*args, answer_style=self._answer_style)
            self.state_changed.emit("正在回答…")
        except (OSError, ValueError) as error:
            self._extraction_failed(str(error))

    def _partial(self, request_id: int, text: str) -> None:
        if request_id == self._request_id and not self._disposed:
            self._answer += text
            self.partial.emit(text)

    def _completed(self, request_id: int, text: str) -> None:
        if request_id != self._request_id or self._disposed:
            return
        self._request_id = None
        self.busy = False
        self.history.extend([self._request_user, {"role": "assistant", "content": text}])
        self._image_bytes = self._request_user = None
        self.completed.emit(text)
        empty = sum(not page.strip() for page in self._pages)
        self.state_changed.emit(f"回答完成 · 全文 {self.page_count} 页" + (f"（{empty} 页无可提取文字）" if empty else ""))

    def _failed(self, request_id: int, message: str) -> None:
        if request_id == self._request_id and not self._disposed:
            self._extraction_failed(message)

    def _extraction_failed(self, message: str) -> None:
        if not self.busy or self._disposed:
            return
        self._request_id = None
        self.busy = False
        self.failed.emit(message)
        self.state_changed.emit(message)

    def cancel(self) -> None:
        request_id, self._request_id = self._request_id, None
        was_busy, self.busy = self.busy, False
        self.loader.cancel()
        self._image_bytes = self._request_user = None
        if request_id is not None:
            self.client.cancel(request_id)
        if was_busy and not self._disposed:
            self.failed.emit("已停止生成")
            self.state_changed.emit("已停止生成")

    def clear(self) -> None:
        self.cancel()
        self.history.clear()
        self.conversation_reset.emit()
        self.state_changed.emit("对话已清空，下一次提问仍会使用全文。")

    def dispose(self) -> None:
        self._disposed = True
        self.cancel()
