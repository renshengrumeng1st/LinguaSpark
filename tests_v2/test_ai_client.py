import json

from learning_assistant.services.ai_client import (
    QtAIClient,
    SSEContentParser,
    extract_response_content,
    parse_json_content,
)
from learning_assistant.domain.models import ModelProfile


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
