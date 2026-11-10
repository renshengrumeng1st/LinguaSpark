import json

import pytest
from PySide6.QtCore import QObject, Signal

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
from tests_v2.test_model_connection import model_server  # noqa: F401 - shared local HTTP fixture


class PendingReply(QObject):
    readyRead = Signal()
    finished = Signal()

    def abort(self):
        self.finished.emit()


class CaptureNetwork:
    """Inspect request construction only; transport is covered by local HTTP tests."""

    def post(self, request, body):
        self.request = request
        self.payload = json.loads(bytes(body))
        self.reply = PendingReply()
        return self.reply


@pytest.mark.parametrize("kind", [QueryKind.WORD, QueryKind.SENTENCE])
def test_deepseek_learning_disables_thinking_and_requests_json(qapp, kind):
    client = QtAIClient(qapp)
    network = CaptureNetwork()
    client.network = network
    client.start(ModelProfile("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash", "test-key"), QueryRequest("chin", kind))
    assert network.payload.get("thinking") == {"type": "disabled"}
    assert network.payload.get("response_format") == {"type": "json_object"}


def test_generic_provider_keeps_its_existing_request_options(qapp):
    client = QtAIClient(qapp)
    network = CaptureNetwork()
    client.network = network
    client.start(ModelProfile("other", "Other", "https://compatible.example/v1", "deepseek-flash", "test-key"), QueryRequest("chin", QueryKind.WORD))
    assert "thinking" not in network.payload
    assert "response_format" not in network.payload


def test_deepseek_connection_probe_disables_thinking(qapp):
    from learning_assistant.services.model_connection import ModelConnectionTester

    tester = ModelConnectionTester(qapp)
    network = CaptureNetwork()
    tester.network = network
    tester.start(ModelProfile("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash", "test-key"))
    try:
        assert network.payload.get("thinking") == {"type": "disabled"}
    finally:
        tester.cancel()


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("kind", [QueryKind.WORD, QueryKind.SENTENCE])
def test_truncated_response_reports_limit_instead_of_parsing_or_saving(qtbot, qapp, model_server, streaming, kind):
    # Even syntactically complete JSON must not hide a length termination.
    text = json.dumps({"plain_explanation": "下巴", "translation": "下巴"}, ensure_ascii=False)
    if streaming:
        model_server.content_type = "text/event-stream"
        frames = [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                  {"choices": [{"delta": {}, "finish_reason": "length"}]}]
        model_server.response_body = ("".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n").encode()
    else:
        model_server.payload = {"choices": [{"message": {"content": text}, "finish_reason": "length"}]}
    client = QtAIClient(qapp)
    completed = []
    client.completed.connect(lambda *args: completed.append(args))
    with qtbot.waitSignal(client.failed, timeout=2500) as signal:
        client.start(ModelProfile("test", "Test", model_server.url, "test-model", "test-key"), QueryRequest("chin", kind))
    assert "截断" in signal.args[1]
    assert not completed


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


def test_content_blocks_are_text_not_python_repr():
    value = {"choices": [{"message": {"content": [
        {"type": "text", "text": '{"translation":'},
        {"type": "text", "text": '"你好"}'},
    ]}}]}
    assert extract_response_content(value) == '{"translation":"你好"}'


@pytest.mark.parametrize("surface", ["learning", "pdf", "probe"])
def test_longcat_uses_current_chat_protocol_on_every_surface(qapp, surface):
    from learning_assistant.domain.models import LanguageProfile
    from learning_assistant.services.pdf_translation import QtPdfTranslationClient
    from learning_assistant.services.model_connection import ModelConnectionTester

    profile = ModelProfile("lc", "Longcat", "https://api.longcat.chat/openai", "LongCat-2.5-Preview", "test-key")
    network = CaptureNetwork()
    if surface == "pdf":
        client = QtPdfTranslationClient(qapp)
        client.network = network
        client.start(profile, "Hello world.", LanguageProfile())
    elif surface == "probe":
        client = ModelConnectionTester(qapp)
        client.network = network
        client.start(profile)
    else:
        client = QtAIClient(qapp)
        client.network = network
        client.start(profile, QueryRequest("chin", QueryKind.WORD))
    try:
        assert network.payload.get("thinking") == {"type": "disabled"}
        if surface == "learning":
            assert network.payload.get("response_format") == {"type": "json_object"}
        assert all(isinstance(m["content"], str) for m in network.payload["messages"])
        assert network.request.url().toString() == "https://api.longcat.chat/openai/v1/chat/completions"
    finally:
        if surface == "probe":
            client.cancel()


@pytest.mark.parametrize("streaming", [True, False])
def test_reasoning_budget_failure_reports_cause_without_exposing_reasoning(qtbot, qapp, model_server, streaming, caplog):
    choice = {"message": {"content": None, "reasoning_content": "private-thought"}, "finish_reason": "length"}
    usage = {"completion_tokens": 1024, "completion_tokens_details": {"reasoning_tokens": 1023}}
    if streaming:
        choice["delta"] = choice.pop("message")
        frames = [{"choices": [choice]}, {"choices": [], "usage": usage}]
        model_server.content_type = "text/event-stream"
        model_server.response_body = ("".join("data: " + json.dumps(f) + "\n\n" for f in frames) + "data: [DONE]\n\n").encode()
    else:
        model_server.payload = {"choices": [choice], "usage": usage}
    client = QtAIClient(qapp)
    partials = []
    client.partial.connect(lambda *args: partials.append(args))
    with qtbot.waitSignal(client.failed, timeout=2500) as signal:
        client.start(ModelProfile("test", "Test", model_server.url, "reasoner", "test-key"), QueryRequest("chin", QueryKind.WORD))
    assert "思考" in signal.args[1] and "预算" in signal.args[1]
    assert "reasoning_tokens=1023" in caplog.text
    assert "private-thought" not in caplog.text + signal.args[1]
    assert not partials


def test_provider_matching_does_not_send_private_options_to_similar_host(qapp):
    from learning_assistant.services.ai_client import provider_request_options
    profile = ModelProfile("test", "Test", "https://bigmodel.attacker.example/v1", "glm-fast")
    assert provider_request_options(profile) == {}


@pytest.mark.parametrize("ending", ["", "\n", "\r\n\r\n"])
def test_sse_final_frame_and_multiline_data_are_not_lost_or_duplicated(ending):
    parser = SSEContentParser()
    raw = ('data: {"choices":\r\n'
           'data: [{"delta":{"content":"hello"},"finish_reason":"stop"}]}' + ending).encode()
    tokens = []
    for byte in raw:
        tokens.extend(parser.feed(bytes([byte])))
    tokens.extend(parser.close())
    assert tokens == ["hello"]
    assert parser.finish_reason == "stop"


@pytest.mark.parametrize("surface", ["learning", "pdf", "probe"])
@pytest.mark.parametrize("payload,expected", [
    ({"error": {"message": "private-provider-message"}}, "返回错误"),
    ({"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}, "过滤"),
    ({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}, "正文"),
])
def test_incomplete_responses_fail_consistently(qtbot, qapp, model_server, surface, payload, expected):
    from learning_assistant.domain.models import LanguageProfile
    from learning_assistant.services.pdf_translation import QtPdfTranslationClient
    from learning_assistant.services.model_connection import ModelConnectionTester
    model_server.payload = payload
    profile = ModelProfile("test", "Test", model_server.url, "test-model", "test-key")
    if surface == "probe":
        client = ModelConnectionTester(qapp)
        signal = client.finished
        start = lambda: client.start(profile)
    elif surface == "pdf":
        client = QtPdfTranslationClient(qapp)
        signal = client.failed
        start = lambda: client.start(profile, "Hello.", LanguageProfile())
    else:
        client = QtAIClient(qapp)
        signal = client.failed
        start = lambda: client.start(profile, QueryRequest("Hello.", QueryKind.SENTENCE))
    with qtbot.waitSignal(signal, timeout=2500) as result:
        start()
    message = result.args[2] if surface == "probe" else result.args[1]
    assert expected in message
    assert "private-provider-message" not in message


@pytest.mark.parametrize("url,model,key,value", [
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-plus", "enable_thinking", False),
    ("https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", "enable_thinking", False),
    ("https://api.moonshot.cn/v1", "kimi-k2.5", "thinking", {"type": "disabled"}),
])
def test_other_vendor_thinking_switches_are_not_assumed_to_be_identical(url, model, key, value):
    from learning_assistant.services.ai_client import provider_request_options
    assert provider_request_options(ModelProfile("", "", url, model))[key] == value


@pytest.mark.parametrize("surface", ["learning", "pdf", "probe"])
def test_openai_reasoning_models_use_supported_token_parameter(qapp, surface):
    from learning_assistant.domain.models import LanguageProfile
    from learning_assistant.services.pdf_translation import QtPdfTranslationClient
    from learning_assistant.services.model_connection import ModelConnectionTester
    profile = ModelProfile("o", "OpenAI", "https://api.openai.com/v1", "o3", "test", max_output_tokens=8192)
    network = CaptureNetwork()
    if surface == "learning":
        client = QtAIClient(qapp)
        client.network = network
        client.start(profile, QueryRequest("hello", QueryKind.WORD))
    elif surface == "pdf":
        client = QtPdfTranslationClient(qapp)
        client.network = network
        client.start(profile, "Hello.", LanguageProfile())
    else:
        client = ModelConnectionTester(qapp)
        client.network = network
        client.start(profile)
    try:
        assert network.payload.get("max_completion_tokens") == 8192
        assert "max_tokens" not in network.payload
        assert "temperature" not in network.payload
    finally:
        if surface == "probe":
            client.cancel()


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
