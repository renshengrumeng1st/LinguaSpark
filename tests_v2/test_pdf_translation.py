from __future__ import annotations

import base64
import importlib
import importlib.util
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import LanguageProfile, ModelProfile
from learning_assistant.domain.pdf_models import (
    PdfPhrase,
    PdfTextSelection,
    PdfTranslationResult,
)
from learning_assistant.storage.learning_repository import LearningRepository


class SandboxSecretStore(SecretStore):
    @classmethod
    def _protect(cls, plaintext: str) -> str:
        return "test:" + base64.b64encode(plaintext.encode()).decode()

    @classmethod
    def _unprotect(cls, encoded: str) -> str:
        if not encoded.startswith("test:"):
            return ""
        return base64.b64decode(encoded[5:]).decode()


class FakePdfClient(QObject):
    translation_partial = Signal(int, str)
    phrase_ready = Signal(int, object)
    completed = Signal(int, object, object)
    failed = Signal(int, str, object)

    def __init__(self):
        super().__init__()
        self.next_id = 0
        self.start_calls: list[tuple[ModelProfile, str, LanguageProfile]] = []
        self.cancel_calls: list[int | None] = []

    def start(
        self, profile: ModelProfile, text: str, languages: LanguageProfile
    ) -> int:
        self.next_id += 1
        self.start_calls.append((profile, text, languages))
        return self.next_id

    def cancel(self, request_id: int | None = None) -> None:
        self.cancel_calls.append(request_id)


def _pdf_modules():
    assert importlib.util.find_spec("learning_assistant.services.pdf_translation") is not None
    assert importlib.util.find_spec("learning_assistant.pdf_controller") is not None
    return (
        importlib.import_module("learning_assistant.services.pdf_translation"),
        importlib.import_module("learning_assistant.pdf_controller"),
    )


def _settings(tmp_path: Path) -> SettingsStore:
    settings = SettingsStore(
        tmp_path / "settings.json",
        SandboxSecretStore(tmp_path / "credentials.json"),
        tmp_path / "missing-legacy.json",
    )
    settings.upsert_model(ModelProfile(
        id="fast-model",
        name="Fast",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-fast",
        api_key="secret-key",
    ))
    return settings


def _selection(text: str = "Take part in the discussion.") -> PdfTextSelection:
    return PdfTextSelection(0, 10, 38, text, ((1.0, 2.0, 30.0, 8.0),))


def test_pdf_request_payload_prioritizes_translation_and_sends_only_selection() -> None:
    pdf_translation, _ = _pdf_modules()
    profile = ModelProfile(
        "glm", "GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-fast", "key"
    )
    languages = LanguageProfile("en", "zh-CN", "zh-CN")

    payload = pdf_translation.QtPdfTranslationClient.build_payload(
        profile, "Only this sentence.", languages
    )
    user = json.loads(payload["messages"][1]["content"])
    system = payload["messages"][0]["content"]

    assert user == {
        "task": "translate_pdf_selection",
        "text": "Only this sentence.",
        "source_language": "en",
        "target_language": "zh-CN",
    }
    assert system.index("translation") < system.index("<<<PHRASES>>>")
    assert "at most 5" in system
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 768
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["stream"] is True


def test_pdf_controller_ignores_late_result_from_cancelled_selection(
    tmp_path: Path,
) -> None:
    _, controller_module = _pdf_modules()
    client = FakePdfClient()
    controller = controller_module.PdfTranslationController(
        _settings(tmp_path),
        LearningRepository(tmp_path / "learning.sqlite3"),
        client,
    )
    partials: list[str] = []
    controller.translation_partial.connect(partials.append)

    controller.set_selection(_selection("First sentence."), "doc")
    controller.translate_selection()
    first_id = client.next_id
    controller.set_selection(_selection("Second sentence."), "doc")
    controller.translate_selection()
    client.translation_partial.emit(first_id, "迟到的旧译文")

    assert partials == []
    assert client.cancel_calls == [first_id]
    assert [call[1] for call in client.start_calls] == [
        "First sentence.",
        "Second sentence.",
    ]


def test_pdf_controller_cache_hit_avoids_a_second_network_request(
    tmp_path: Path,
) -> None:
    _, controller_module = _pdf_modules()
    settings = _settings(tmp_path)
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    first_client = FakePdfClient()
    first = controller_module.PdfTranslationController(
        settings, repository, first_client
    )
    first.set_selection(_selection(), "doc")
    first.translate_selection()
    result = PdfTranslationResult(
        "参加讨论。", (PdfPhrase("take part", "参加"),)
    )
    first_client.completed.emit(
        first_client.next_id,
        result,
        {"first_byte_ms": 120, "total_ms": 450},
    )

    cached_client = FakePdfClient()
    cached = controller_module.PdfTranslationController(
        settings, repository, cached_client
    )
    completed: list[tuple[PdfTranslationResult, bool]] = []
    cached.translation_completed.connect(
        lambda value, cache_hit: completed.append((value, cache_hit))
    )
    cached.set_selection(_selection(), "doc")
    cached.translate_selection()

    assert cached_client.start_calls == []
    assert completed == [(result, True)]


def test_pdf_controller_persists_and_deletes_current_highlight(
    tmp_path: Path,
) -> None:
    _, controller_module = _pdf_modules()
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    controller = controller_module.PdfTranslationController(
        _settings(tmp_path), repository, FakePdfClient()
    )
    changes: list[list] = []
    controller.annotations_changed.connect(changes.append)
    controller.set_selection(_selection(), "doc")

    controller.add_highlight("pink")
    controller.delete_highlight()

    assert changes[0][0].color == "pink"
    assert changes[-1] == []


def test_shared_pdf_client_keeps_tab_requests_isolated_and_disposable(
    tmp_path: Path,
) -> None:
    _, controller_module = _pdf_modules()
    settings = _settings(tmp_path)
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    client = FakePdfClient()
    first = controller_module.PdfTranslationController(
        settings, repository, client
    )
    second = controller_module.PdfTranslationController(
        settings, repository, client
    )
    first_partials: list[str] = []
    second_partials: list[str] = []
    first.translation_partial.connect(first_partials.append)
    second.translation_partial.connect(second_partials.append)
    first.set_selection(_selection("First tab."), "first-doc")
    second.set_selection(_selection("Second tab."), "second-doc")

    first.translate_selection()
    first_id = client.next_id
    second.translate_selection()
    second_id = client.next_id
    client.translation_partial.emit(second_id, "第二个标签")

    assert first_partials == []
    assert second_partials == ["第二个标签"]
    assert first.active_request_id == first_id
    assert second.active_request_id == second_id

    first.dispose()
    first.dispose()
    client.translation_partial.emit(first_id, "迟到结果")
    client.translation_partial.emit(second_id, "继续接收")

    assert first_partials == []
    assert second_partials == ["第二个标签", "继续接收"]
    assert client.cancel_calls == [first_id]
    assert first.active_request_id is None
    assert second.active_request_id == second_id
