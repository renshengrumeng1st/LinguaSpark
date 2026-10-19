import json

import pytest

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.services.ai_client import (
    QtAIClient,
    SSEContentParser,
    StreamingTranslationExtractor,
    extract_response_content,
    parse_json_content,
)
from learning_assistant.domain.models import ModelProfile, QueryKind, QueryRequest
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.storage.learning_repository import LearningRepository


def test_sse_parser_handles_split_frames():
    parser = SSEContentParser()
    first = {"choices": [{"delta": {"content": "{\"translation\":"}}]}
    second = {"choices": [{"delta": {"content": "\"你好\"}"}}]}
    encoded = (
        "data: " + json.dumps(first) + "\n\n" +
        "data: " + json.dumps(second) + "\n\n" +
        "data: [DONE]\n\n"
    ).encode()
    middle = len(encoded) // 2
    chunks = parser.feed(encoded[:middle]) + parser.feed(encoded[middle:])
    assert "".join(chunks) == '{"translation":"你好"}'


def test_parse_json_content_accepts_fenced_json():
    assert parse_json_content('```json\n{"translation":"自然译文"}\n```') == {
        "translation": "自然译文"
    }


def test_extract_non_stream_response():
    value = {"choices": [{"message": {"content": "done"}}]}
    assert extract_response_content(value) == "done"


def test_glm_keeps_supported_system_role():
    profile = ModelProfile("glm", "GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4.5-air")
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "text"}]
    assert QtAIClient._provider_messages(profile, messages) == messages


def test_controller_streams_only_decoded_sentence_translation(tmp_path):
    settings = SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "no-legacy.json",
    )
    controller = LearningController(
        settings,
        DictionaryRepository(tmp_path / "missing.sqlite3"),
        LearningRepository(tmp_path / "learning.sqlite3"),
    )
    controller._active = QueryRequest("Hello", QueryKind.SENTENCE)
    controller._active_request_id = 7
    updates = []
    controller.ai_partial.connect(updates.append)

    for chunk in (
        '{"translation":"你',
        '好\\n世',
        '界","key_phrases":[{"phrase":"Hello","meaning":"你好"}]}',
    ):
        controller.ai.partial.emit(7, chunk)

    assert updates == ["你", "你好\n世", "你好\n世界"]
    controller.ai.partial.emit(6, '{"translation":"旧请求"}')
    assert updates[-1] == "你好\n世界"


def test_word_stream_does_not_show_raw_json(tmp_path):
    settings = SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "no-legacy.json",
    )
    controller = LearningController(
        settings,
        DictionaryRepository(tmp_path / "missing.sqlite3"),
        LearningRepository(tmp_path / "learning.sqlite3"),
    )
    controller._active = QueryRequest("hello", QueryKind.WORD)
    controller._active_request_id = 8
    updates = []
    controller.ai_partial.connect(updates.append)
    controller.ai.partial.emit(8, '{"plain_explanation":"问候"}')
    assert updates == []


def test_streaming_translation_waits_for_complete_unicode_escape():
    stream = StreamingTranslationExtractor()
    assert stream.feed('{"translation":"A\\uD83D') == "A"
    assert stream.feed('\\uDE') is None
    assert stream.feed('00 and \\"quote\\""') == 'A😀 and "quote"'
    assert stream.feed(',"learning_tip":"not part of translation"}') is None


@pytest.mark.parametrize("translation", [
    "C:\\",
    "literal \\u123",
    "literal \\uD83D",
    "quote: \" and slash: \\",
])
def test_streaming_translation_preserves_literal_escapes_at_every_split(translation):
    content = json.dumps({"translation": translation}, ensure_ascii=True)
    for split in range(len(content) + 1):
        stream = StreamingTranslationExtractor()
        updates = [stream.feed(content[:split]), stream.feed(content[split:])]
        emitted = [value for value in updates if value is not None]
        assert emitted[-1:] == [translation], (split, emitted)
