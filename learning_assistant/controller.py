"""Application orchestration, independent from concrete widgets."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from PySide6.QtCore import QObject, Signal

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import (
    AiStudyNote,
    DictionaryEntry,
    QueryKind,
    QueryRequest,
    SentenceResult,
)
from learning_assistant.services.ai_client import PROMPT_VERSION, QtAIClient
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.storage.learning_repository import LearningRepository


class LearningController(QObject):
    query_started = Signal(object)
    word_ready = Signal(object, int)  # entry, local milliseconds
    ai_note_ready = Signal(object, bool)  # note, cache hit
    sentence_ready = Signal(object, bool)
    ai_partial = Signal(str)
    query_failed = Signal(str)
    query_finished = Signal(object)
    favorite_changed = Signal(bool)
    study_changed = Signal(bool)

    def __init__(
        self,
        settings: SettingsStore,
        dictionary: DictionaryRepository | None = None,
        repository: LearningRepository | None = None,
        ai: QtAIClient | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.dictionary = dictionary or DictionaryRepository()
        self.repository = repository or LearningRepository()
        self.ai = ai or QtAIClient(self)
        self.ai.partial.connect(self._on_partial)
        self.ai.completed.connect(self._on_ai_complete)
        self.ai.failed.connect(self._on_ai_failed)
        self._active_request_id: int | None = None
        self._active: QueryRequest | None = None
        self._active_entry: DictionaryEntry | None = None
        self._active_cache_key = ""
        self._active_model_id = ""
        self._current_payload: dict[str, Any] = {}

    @staticmethod
    def classify(text: str, has_image: bool = False) -> QueryKind:
        if has_image:
            return QueryKind.IMAGE
        if DictionaryRepository.is_word(text):
            return QueryKind.WORD
        return QueryKind.SENTENCE

    def cancel(self) -> None:
        if self._active_request_id is not None:
            self.ai.cancel(self._active_request_id)

    def submit(self, text: str, context: str = "", image_bytes: bytes | None = None) -> None:
        text = text.strip()
        if not text and not image_bytes:
            self.query_failed.emit("请输入单词、句子或粘贴图片")
            return
        self.cancel()
        kind = self.classify(text, bool(image_bytes))
        request = QueryRequest(
            text=text,
            kind=kind,
            languages=self.settings.languages(),
            context=context.strip(),
            image_bytes=image_bytes,
        )
        self._active = request
        self._active_entry = None
        self._active_model_id = ""
        self._current_payload = {}
        self.query_started.emit(request)

        if kind == QueryKind.WORD:
            started = time.perf_counter()
            entry = self.dictionary.lookup(text, request.languages.source)
            local_ms = round((time.perf_counter() - started) * 1000)
            self._active_entry = entry
            if entry:
                self._current_payload["dictionary"] = asdict(entry)
                self.word_ready.emit(entry, local_ms)

        profile = self.settings.active_model()
        if not profile or not profile.api_key:
            self._active_request_id = None
            if kind == QueryKind.WORD and self._active_entry:
                self.query_finished.emit({"local_only": True})
            else:
                self.query_failed.emit("请先在设置中添加并选择 AI 模型")
            return

        self._active_model_id = profile.id

        dictionary_facts = self._active_entry.to_prompt_dict() if self._active_entry else {}
        self._active_cache_key = self.repository.stable_key(
            PROMPT_VERSION,
            profile.id,
            profile.base_url,
            profile.model,
            request.kind.value,
            request.text,
            request.context,
            request.languages.source,
            request.languages.target,
            request.languages.explanation,
            dictionary_facts,
        )
        cached = self.repository.get_ai_cache(self._active_cache_key)
        if cached:
            self._active_request_id = None
            self._apply_structured_result(cached, cache_hit=True)
            return
        self._active_request_id = self.ai.start(profile, request, self._active_entry)

    def _on_partial(self, request_id: int, text: str) -> None:
        if request_id == self._active_request_id:
            self.ai_partial.emit(text)

    def _on_ai_complete(
        self, request_id: int, structured: dict[str, Any], timings: dict[str, Any]
    ) -> None:
        if request_id != self._active_request_id or not self._active:
            return
        if self._active_model_id:
            self.repository.record_metric(
                self._active_model_id,
                self._active.kind.value,
                timings.get("first_byte_ms"),
                int(timings.get("total_ms") or 0),
                True,
            )
        self.repository.put_ai_cache(self._active_cache_key, structured)
        self._active_request_id = None
        self._apply_structured_result(structured, cache_hit=False)

    def _apply_structured_result(self, structured: dict[str, Any], cache_hit: bool) -> None:
        if not self._active:
            return
        if self._active.kind == QueryKind.WORD:
            note = AiStudyNote.from_dict(structured)
            self._current_payload["ai_note"] = note.to_dict()
            self.ai_note_ready.emit(note, cache_hit)
        else:
            result = SentenceResult.from_dict(structured)
            self._current_payload["sentence"] = asdict(result)
            self.sentence_ready.emit(result, cache_hit)
        self.repository.add_history(
            self._active.text,
            self._active.kind.value,
            self._current_payload,
            self._active.languages.source,
            self._active.languages.target,
        )
        if self.repository.is_learning_item(self._active.text, self._active.kind.value):
            self.repository.update_learning_payload(
                self._active.text, self._active.kind.value, self._current_payload
            )
        self.query_finished.emit({"cache_hit": cache_hit})

    def _on_ai_failed(
        self, request_id: int, message: str, timings: dict[str, Any]
    ) -> None:
        if request_id != self._active_request_id:
            return
        if self._active_model_id and self._active:
            self.repository.record_metric(
                self._active_model_id,
                self._active.kind.value,
                timings.get("first_byte_ms"),
                int(timings.get("total_ms") or 0),
                False,
            )
        self._active_request_id = None
        self.query_failed.emit(message)

    def toggle_favorite(self) -> bool:
        if not self._active:
            return False
        active = self.repository.toggle_favorite(
            self._active.text,
            self._active.kind.value,
            self._current_payload,
            self._active.context,
        )
        self.favorite_changed.emit(active)
        return active

    def is_current_favorite(self) -> bool:
        if not self._active:
            return False
        return self.repository.is_favorite(self._active.text, self._active.kind.value)

    def toggle_study(self) -> bool:
        if not self._active or self._active.kind != QueryKind.WORD:
            return False
        active = self.repository.toggle_learning_item(
            self._active.text,
            self._active.kind.value,
            self._current_payload,
            self._active.context,
            self._active.languages.source,
            self._active.languages.target,
        )
        self.study_changed.emit(active)
        return active

    def is_current_study(self) -> bool:
        if not self._active or self._active.kind != QueryKind.WORD:
            return False
        return self.repository.is_learning_item(self._active.text, self._active.kind.value)
