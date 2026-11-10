"""PDF selection orchestration independent from concrete reader widgets."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtCore import QObject, Signal

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.pdf_models import (
    PdfPhrase,
    PdfTextSelection,
    PdfTranslationResult,
)
from learning_assistant.services.pdf_text import document_key, normalize_pdf_selection
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
    learning_changed = Signal()
    learning_failed = Signal(str)

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
        self._completed_selection: PdfTextSelection | None = None
        self._completed_result: PdfTranslationResult | None = None
        self._completed_document_key = ""

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
        self._completed_selection = None
        self._completed_result = None
        self._completed_document_key = ""
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
        self.cancel()
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
            result = self._result_from_payload(cached)
            self._accept_completed_result(result)
            self.translation_completed.emit(
                result, True
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
        self._accept_completed_result(result)
        self.translation_completed.emit(result, False)

    def _accept_completed_result(self, result: PdfTranslationResult) -> None:
        self._completed_result = result
        self._completed_selection = self._selection
        self._completed_document_key = self._document_key

    def is_phrase_in_learning(self, phrase: PdfPhrase) -> bool:
        return self.repository.is_learning_item(phrase.source.strip(), "word")

    def add_phrase_to_learning(self, phrase: PdfPhrase, document_path: str) -> bool:
        selection, result = self._completed_selection, self._completed_result
        if (self._disposed or selection is None or result is None
                or selection != self._selection or self._completed_document_key != self._document_key
                or phrase not in result.phrases or not phrase.source.strip() or not phrase.meaning.strip()):
            self.learning_failed.emit("请先完成当前选区翻译，再加入学习。")
            return False
        try:
            path = Path(document_path).resolve()
            if not document_path or path.suffix.casefold() != ".pdf" or not path.is_file():
                raise ValueError("PDF 来源不可用，请重新打开文件后再加入学习。")
            if document_key(path) != self._completed_document_key:
                raise ValueError("PDF 来源已变化，请重新打开文件并翻译后再加入学习。")
            languages = self.settings.languages()
            payload = {
                "dictionary": {"word": phrase.source.strip(), "translations": [phrase.meaning.strip()]},
                "ai_note": {"examples": [{"sentence": selection.text, "translation": result.translation}]},
                "pdf_source": {"path": str(path), "document_key": self._completed_document_key,
                               "page_index": selection.page_index, "selected_text": selection.text,
                               "translation": result.translation},
            }
            self.repository.add_learning_item(
                phrase.source.strip(), "word", payload, selection.text,
                languages.source, languages.target,
            )
        except ValueError as error:
            self.learning_failed.emit(str(error))
            return False
        except (OSError, sqlite3.Error):
            self.learning_failed.emit("保存学习项目失败，请检查来源文件和数据目录权限。")
            return False
        self.learning_changed.emit()
        return True

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
