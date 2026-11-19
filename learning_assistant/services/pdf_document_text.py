"""Cancellable, page-preserving local PDF extraction outside the GUI thread."""

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from learning_assistant.services.pdf_text import document_key

MAX_DOCUMENT_CHARS = 200_000


class _ExtractionSignals(QObject):
    loaded = Signal(int, object)
    failed = Signal(int, str)


class _ExtractionJob(QRunnable):
    def __init__(self, generation: int, path: Path, stopped: Event, *, allow_empty=False):
        super().__init__()
        self.generation, self.path, self.stopped = generation, path, stopped
        self.allow_empty = allow_empty
        self.signals = _ExtractionSignals()

    def run(self) -> None:
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        try:
            identity = document_key(self.path)
            error = document.load(str(self.path))
            if error != QPdfDocument.Error.None_:
                raise ValueError("无法提取 PDF 全文；请检查文件。加密 PDF 请先使用解密副本。")
            pages, total = [], 0
            for index in range(document.pageCount()):
                if self.stopped.is_set():
                    return
                text = document.getAllText(index).text().strip()
                total += len(text)
                if total > MAX_DOCUMENT_CHARS:
                    raise ValueError("PDF 全文超过 200,000 字符，未删减或发送。请使用较短的文档。")
                pages.append(text)
            if not any(pages) and not self.allow_empty:
                raise ValueError("PDF 没有可提取文字；扫描版暂不支持全文提问。")
            if document_key(self.path) != identity:
                raise ValueError("PDF 文件已变化，请重新打开后提问。")
            if not self.stopped.is_set():
                self.signals.loaded.emit(self.generation, tuple(pages))
        except (OSError, ValueError, RuntimeError) as error:
            if not self.stopped.is_set():
                self.signals.failed.emit(self.generation, str(error))
        finally:
            document.close()


class PdfDocumentTextLoader(QObject):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._stopped = Event()

    def load(self, path: Path, *, allow_empty=False) -> None:
        self.cancel()
        self._stopped = Event()
        job = _ExtractionJob(self._generation, Path(path), self._stopped, allow_empty=allow_empty)
        job.signals.loaded.connect(self._on_loaded)
        job.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(job)

    def cancel(self) -> None:
        self._stopped.set()
        self._generation += 1

    def _on_loaded(self, generation: int, pages: tuple[str, ...]) -> None:
        if generation == self._generation and not self._stopped.is_set():
            self.loaded.emit(pages)

    def _on_failed(self, generation: int, message: str) -> None:
        if generation == self._generation and not self._stopped.is_set():
            self.failed.emit(message)
