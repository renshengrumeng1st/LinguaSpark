"""PDF selection orchestration independent from concrete reader widgets."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.pdf_models import (
    PdfPhrase,
    PdfTextSelection,
    PdfTranslationResult,
)
from learning_assistant.services.pdf_text import normalize_pdf_selection
from learning_assistant.services.pdf_translation import (
    PDF_PROMPT_VERSION,
    QtPdfTranslationClient,
)
from learning_assistant.storage.learning_repository import LearningRepository


class PdfTranslationController(QObject):
    selection_changed = Signal(object)
    translation_started = Signal(str)
    translation_partial = Signal(str)
    phrase_ready = Signal(object)
    translation_completed = Signal(object, bool)
    translation_failed = Signal(str)
    annotations_changed = Signal(object)

    def __init__(
        self,
        settings: SettingsStore,
        repository: LearningRepository,
        client: QtPdfTranslationClient | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.repository = repository
        self.client = client or QtPdfTranslationClient(self)
        self.client.translation_partial.connect(self._on_partial)
        self.client.phrase_ready.connect(self._on_phrase)
        self.client.completed.connect(self._on_completed)
        self.client.failed.connect(self._on_failed)
        self._selection: PdfTextSelection | None = None
        self._document_key = ""
        self._active_request_id: int | None = None
        self._active_cache_key = ""
        self._active_model_id = ""
        self._disposed = False

    @property
    def selection(self) -> PdfTextSelection | None:
        return self._selection

    @property
    def active_request_id(self) -> int | None:
        return self._active_request_id

    def set_selection(
        self, selection: PdfTextSelection | None, document_key: str
    ) -> None:
        if self._disposed:
            return
        self.cancel()
        self._selection = selection
        self._document_key = document_key
        self.selection_changed.emit(selection)

    def cancel(self) -> None:
        if self._active_request_id is not None:
            self.client.cancel(self._active_request_id)
            self._active_request_id = None

    def dispose(self) -> None:
        if self._disposed:
            return
        self.cancel()
        connections = (
            (self.client.translation_partial, self._on_partial),
            (self.client.phrase_ready, self._on_phrase),
            (self.client.completed, self._on_completed),
            (self.client.failed, self._on_failed),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._disposed = True

    @staticmethod
    def _result_from_payload(payload: dict) -> PdfTranslationResult:
        phrases: list[PdfPhrase] = []
        for item in payload.get("phrases", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            meaning = str(item.get("meaning", "")).strip()
            if source and meaning:
                phrases.append(PdfPhrase(source, meaning))
        return PdfTranslationResult(
            str(payload.get("translation", "")).strip(), tuple(phrases[:5])
        )

    @staticmethod
    def _result_payload(result: PdfTranslationResult) -> dict:
        return {
            "translation": result.translation,
            "phrases": [
                {"source": phrase.source, "meaning": phrase.meaning}
                for phrase in result.phrases
            ],
        }

    def translate_selection(self) -> None:
        if self._disposed:
            return
        if not self._selection:
            self.translation_failed.emit("请先在 PDF 中选择文字")
            return
        try:
            text = normalize_pdf_selection(self._selection.text)
        except ValueError as exc:
            self.translation_failed.emit(str(exc))
            return
        if not text:
            self.translation_failed.emit("当前页面没有可选择文字")
            return
        profile = self.settings.active_model()
        if not profile or not profile.api_key:
            self.translation_failed.emit("请先在设置中添加并选择 AI 模型")
            return
        self.cancel()
        languages = self.settings.languages()
        cache_key = self.repository.stable_key(
            PDF_PROMPT_VERSION,
            profile.id,
            profile.base_url,
            profile.model,
            "pdf_selection",
            text,
            languages.source,
            languages.target,
        )
        self.translation_started.emit(text)
        cached = self.repository.get_ai_cache(cache_key)
        if cached:
            self.translation_completed.emit(
                self._result_from_payload(cached), True
            )
            return
        self._active_cache_key = cache_key
        self._active_model_id = profile.id
        self._active_request_id = self.client.start(profile, text, languages)

    def _on_partial(self, request_id: int, text: str) -> None:
        if not self._disposed and request_id == self._active_request_id:
            self.translation_partial.emit(text)

    def _on_phrase(self, request_id: int, phrase: PdfPhrase) -> None:
        if not self._disposed and request_id == self._active_request_id:
            self.phrase_ready.emit(phrase)

    def _on_completed(
        self,
        request_id: int,
        result: PdfTranslationResult,
        timings: dict,
    ) -> None:
        if self._disposed or request_id != self._active_request_id:
            return
        self.repository.record_metric(
            self._active_model_id,
            "pdf_selection",
            timings.get("first_byte_ms"),
            int(timings.get("total_ms") or 0),
            True,
        )
        self.repository.put_ai_cache(
            self._active_cache_key, self._result_payload(result)
        )
        self._active_request_id = None
        self.translation_completed.emit(result, False)

    def _on_failed(self, request_id: int, message: str, timings: dict) -> None:
        if self._disposed or request_id != self._active_request_id:
            return
        self.repository.record_metric(
            self._active_model_id,
            "pdf_selection",
            timings.get("first_byte_ms"),
            int(timings.get("total_ms") or 0),
            False,
        )
        self._active_request_id = None
        self.translation_failed.emit(message)

    def annotations(self):
        if not self._document_key:
            return []
        return self.repository.pdf_annotations(self._document_key)

    def add_highlight(self, color: str) -> None:
        if self._disposed or not self._selection or not self._document_key:
            return
        if not self._selection.can_annotate:
            self.translation_failed.emit("当前选区可以翻译，但无法稳定标记")
            return
        self.repository.add_pdf_annotation(
            self._document_key, self._selection, color
        )
        self.annotations_changed.emit(self.annotations())

    def delete_highlight(self) -> bool:
        if self._disposed or not self._selection or not self._document_key:
            return False
        if not self._selection.can_annotate:
            return False
        deleted = self.repository.delete_pdf_annotation(
            self._document_key,
            self._selection.page_index,
            self._selection.start_index,
            self._selection.end_index,
        )
        self.annotations_changed.emit(self.annotations())
        return deleted
