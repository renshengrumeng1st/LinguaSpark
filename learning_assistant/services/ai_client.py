"""Qt-native OpenAI-compatible client with real cancellation and timings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from learning_assistant.domain.models import DictionaryEntry, ModelProfile, QueryKind, QueryRequest
from learning_assistant.services.model_providers import api_endpoint, provider_options


PROMPT_VERSION = "learning-v2.2"
OUTPUT_LIMIT_MESSAGE = "模型输出达到上限，内容被截断。请在模型配置中提高输出预算，或更换模型。"
logger = logging.getLogger(__name__)


def provider_request_options(profile: ModelProfile, *, json_output: bool = False) -> dict[str, Any]:
    """Keep bounded learning requests out of providers' default thinking mode."""
    return provider_options(profile.base_url, profile.model, json_output=json_output)


def chat_request_payload(
    profile: ModelProfile,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
    temperature: float | None = None,
    json_output: bool = False,
) -> dict[str, Any]:
    """Use the same request contract for learning, PDF, and connection probes."""
    payload: dict[str, Any] = {
        "model": profile.model.strip(), "messages": messages, "stream": stream,
    }
    model = profile.model.casefold()
    openai_reasoning = QUrl(profile.base_url).host().casefold() == "api.openai.com" and (
        re.match(r"^o[134](?:-|$)", model) is not None or model.startswith("gpt-5")
    )
    payload["max_completion_tokens" if openai_reasoning else "max_tokens"] = profile.max_output_tokens
    if temperature is not None and not openai_reasoning:
        payload["temperature"] = temperature
    payload.update(provider_request_options(profile, json_output=json_output))
    return payload


def response_finish_reason(value: Any) -> str | None:
    if isinstance(value, dict):
        choices = value.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            reason = choices[0].get("finish_reason")
            if isinstance(reason, str) and reason:
                return reason
    return None


class SSEContentParser:
    """Incrementally extracts content tokens from OpenAI-style SSE frames."""

    def __init__(self):
        self.buffer = b""
        self.content: list[str] = []
        self.finish_reason: str | None = None
        self.reasoning_chars = 0
        self.usage: dict[str, Any] = {}
        self.api_error = False
        self._data_lines: list[bytes] = []

    def observe(self, value: Any) -> None:
        """Retain diagnostic counts, never reasoning text or provider secrets."""
        if not isinstance(value, dict):
            return
        self.finish_reason = response_finish_reason(value) or self.finish_reason
        self.api_error = self.api_error or bool(value.get("error"))
        if isinstance(value.get("usage"), dict):
            self.usage.update(value["usage"])
        choices = value.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            message = choice.get("delta") or choice.get("message") or {}
            if isinstance(message, dict):
                reasoning = message.get("reasoning_content") or message.get("reasoning")
                if isinstance(reasoning, str):
                    self.reasoning_chars += len(reasoning)

    def failure_message(self, text: str) -> str | None:
        if self.api_error:
            return "模型服务返回错误，请检查账户额度、模型权限或稍后重试。"
        details = self.usage.get("completion_tokens_details")
        reasoning_tokens = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
        if self.finish_reason == "length":
            if not text.strip() and (self.reasoning_chars or reasoning_tokens):
                return "模型的思考已耗尽输出预算，正文尚未生成而被截断。请提高模型配置中的输出预算，或使用支持关闭思考的模型。"
            return OUTPUT_LIMIT_MESSAGE
        if self.finish_reason in {"content_filter", "safety"}:
            return "模型服务因内容过滤未完成回答，请调整输入后重试。"
        if self.finish_reason in {"tool_calls", "function_call"}:
            return "模型返回了工具调用，未完成学习内容，请选择支持直接文本回答的模型。"
        if not text.strip():
            return "模型没有返回正文，请检查模型的思考模式、输出预算和接口兼容性。"
        return None

    def log_failure(self, profile: ModelProfile, kind: str, text: str) -> None:
        details = self.usage.get("completion_tokens_details")
        reasoning_tokens = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
        logger.warning(
            "AI response incomplete: provider=%s model=%s kind=%s finish_reason=%s "
            "content_chars=%d reasoning_chars=%d completion_tokens=%s reasoning_tokens=%s budget=%d",
            QUrl(profile.base_url).host(), profile.model, kind, self.finish_reason,
            len(text), self.reasoning_chars, self.usage.get("completion_tokens"),
            reasoning_tokens, profile.max_output_tokens,
        )

    def feed(self, data: bytes) -> list[str]:
        self.buffer += data
        emitted: list[str] = []
        while b"\n" in self.buffer:
            raw, self.buffer = self.buffer.split(b"\n", 1)
            raw = raw.rstrip(b"\r")
            if raw.startswith(b"data:"):
                self._data_lines.append(raw[5:].lstrip(b" "))
                continue
            if raw or not self._data_lines:
                continue
            payload = b"\n".join(self._data_lines).strip()
            self._data_lines.clear()
            if not payload or payload == b"[DONE]":
                continue
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            self.observe(value)
            text = extract_response_content(value)
            if text:
                self.content.append(text)
                emitted.append(text)
        return emitted

    def close(self) -> list[str]:
        # feed already owns the pending bytes; appending them again duplicates
        # an unterminated final frame. Flush both its line and event delimiter.
        return self.feed(b"\n\n")


def extract_response_content(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    choices = value.get("choices") or []
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return _text_content(delta["content"])
        message = choice.get("message")
        if isinstance(message, dict) and message.get("content"):
            return _text_content(message["content"])
        if choice.get("content"):
            return _text_content(choice["content"])
    return _text_content(value.get("content"))


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part["text"] for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            and isinstance(part.get("text"), str)
        )
    return ""


def parse_json_content(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


class StreamingTranslationExtractor:
    """Expose only the decoded translation field while JSON is still arriving."""

    def __init__(self):
        self._content = ""
        self._last_translation = ""

    def feed(self, chunk: str) -> str | None:
        self._content += chunk
        match = re.search(r'"translation"\s*:\s*"', self._content)
        if not match:
            return None

        raw_value = self._content[match.end():]
        end = 0
        escaped = False
        for character in raw_value:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                break
            end += 1
        fragment = raw_value[:end]
        if escaped:
            fragment = fragment[:-1]
        incomplete_unicode = re.search(
            r"(?<!\\)(?:\\\\)*(\\u[0-9a-fA-F]{0,3})$", fragment,
        )
        if incomplete_unicode:
            fragment = fragment[:incomplete_unicode.start(1)]
        # A split surrogate pair is not displayable until its low half arrives.
        incomplete_surrogate = re.search(
            r"(?<!\\)(?:\\\\)*(\\u[dD][89aAbB][0-9a-fA-F]{2})$", fragment,
        )
        if incomplete_surrogate:
            fragment = fragment[:incomplete_surrogate.start(1)]
        try:
            translation = json.loads('"' + fragment + '"')
        except json.JSONDecodeError:
            return None
        if translation and translation != self._last_translation:
            self._last_translation = translation
            return translation
        return None


@dataclass(slots=True)
class RequestContext:
    request_id: int
    profile: ModelProfile
    kind: QueryKind
    parser: SSEContentParser
    started_at: float
    first_byte_at: float | None = None
    raw: bytearray | None = None


class QtAIClient(QObject):
    partial = Signal(int, str)
    completed = Signal(int, object, object)  # request id, structured dict, timings
    failed = Signal(int, str, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.network.setTransferTimeout(35_000)
        self._next_id = 0
        self._requests: dict[QNetworkReply, RequestContext] = {}

    @staticmethod
    def _word_messages(request: QueryRequest, entry: DictionaryEntry | None) -> list[dict[str, Any]]:
        facts = entry.to_prompt_dict() if entry else {}
        system = (
            "You are a precise language-learning tutor. The dictionary facts are authoritative. "
            "Explain rather than repeat them. Never invent pronunciation or definitions. "
            "Return JSON only with keys plain_explanation, sense_in_context, synonyms, "
            "collocations, common_mistake, memory_tip, examples. synonyms and collocations "
            "are short string arrays. examples is an array of {sentence, translation}. "
            "Use at most 3 synonyms, 4 collocations and 2 natural examples."
        )
        user = {
            "task": "word_learning_assistance",
            "word": request.text,
            "context": request.context,
            "source_language": request.languages.source,
            "explanation_language": request.languages.explanation,
            "dictionary_facts": facts,
        }
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]

    @staticmethod
    def _sentence_messages(request: QueryRequest) -> list[dict[str, Any]]:
        system = (
            "You are a concise language-learning translation tutor. Return JSON only with "
            "keys translation, key_phrases, learning_tip. key_phrases is an array of at most "
            "4 objects {phrase, meaning}. learning_tip is one short, genuinely useful grammar "
            "or usage note; leave it empty when none is needed. Preserve meaning and use natural "
            "target-language phrasing."
        )
        if request.kind == QueryKind.IMAGE:
            content: list[dict[str, Any]] = [{
                "type": "text",
                "text": json.dumps({
                    "task": "translate_image_text",
                    "additional_text": request.text,
                    "source_language": request.languages.source,
                    "target_language": request.languages.target,
                }, ensure_ascii=False),
            }]
            if request.image_bytes:
                import base64
                encoded = base64.b64encode(request.image_bytes).decode("ascii")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                })
            user_content: str | list[dict[str, Any]] = content
        else:
            user_content = json.dumps({
                "task": "translate_sentence",
                "text": request.text,
                "source_language": request.languages.source,
                "target_language": request.languages.target,
            }, ensure_ascii=False)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _provider_messages(profile: ModelProfile, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Chat Completions uses strings for text and image_url for vision.
        # Responses API input_image parts must not be sent to this endpoint.
        return messages

    def start(
        self,
        profile: ModelProfile,
        request: QueryRequest,
        entry: DictionaryEntry | None = None,
    ) -> int:
        self._next_id += 1
        request_id = self._next_id
        messages = (
            self._word_messages(request, entry)
            if request.kind == QueryKind.WORD else self._sentence_messages(request)
        )
        messages = self._provider_messages(profile, messages)
        payload = chat_request_payload(
            profile, messages, stream=True, temperature=0.2,
            json_output=request.kind != QueryKind.IMAGE,
        )
        endpoint = api_endpoint(profile.base_url, "chat/completions")
        network_request = QNetworkRequest(QUrl(endpoint))
        network_request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        network_request.setRawHeader(b"Accept", b"text/event-stream, application/json")
        network_request.setRawHeader(
            b"Authorization", QByteArray(f"Bearer {profile.api_key}".encode("utf-8"))
        )
        network_request.setTransferTimeout(35_000)
        reply = self.network.post(
            network_request,
            QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        )
        self._requests[reply] = RequestContext(
            request_id=request_id,
            profile=profile,
            kind=request.kind,
            parser=SSEContentParser(),
            started_at=time.perf_counter(),
            raw=bytearray(),
        )
        reply.readyRead.connect(lambda current=reply: self._on_ready_read(current))
        reply.finished.connect(lambda current=reply: self._on_finished(current))
        return request_id

    def cancel(self, request_id: int | None = None) -> None:
        for reply, context in list(self._requests.items()):
            if request_id is None or context.request_id == request_id:
                reply.abort()

    def _on_ready_read(self, reply: QNetworkReply) -> None:
        context = self._requests.get(reply)
        if not context:
            return
        data = bytes(reply.readAll())
        if not data:
            return
        if context.first_byte_at is None:
            context.first_byte_at = time.perf_counter()
        context.raw.extend(data)
        for token in context.parser.feed(data):
            self.partial.emit(context.request_id, token)

    @staticmethod
    def _timings(context: RequestContext) -> dict[str, int | None]:
        finished = time.perf_counter()
        return {
            "first_byte_ms": (
                round((context.first_byte_at - context.started_at) * 1000)
                if context.first_byte_at else None
            ),
            "total_ms": round((finished - context.started_at) * 1000),
        }

    def _on_finished(self, reply: QNetworkReply) -> None:
        context = self._requests.get(reply)
        if not context:
            reply.deleteLater()
            return
        if reply.bytesAvailable():
            self._on_ready_read(reply)
        self._requests.pop(reply, None)
        for token in context.parser.close():
            self.partial.emit(context.request_id, token)
        timings = self._timings(context)
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        error = reply.error()
        if error != QNetworkReply.NetworkError.NoError:
            if error == QNetworkReply.NetworkError.OperationCanceledError:
                message = "请求已取消"
            elif status == 401:
                message = "API 认证失败，请检查密钥"
            elif status == 429:
                message = "请求过于频繁，请稍后重试"
            else:
                message = reply.errorString() or f"网络请求失败（HTTP {status or '-'}）"
            self.failed.emit(context.request_id, message, timings)
            reply.deleteLater()
            return

        text = "".join(context.parser.content)
        if not text:
            try:
                response = json.loads(bytes(context.raw or b"{}"))
                text = extract_response_content(response)
                context.parser.observe(response)
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = ""
        failure = context.parser.failure_message(text)
        if failure:
            context.parser.log_failure(context.profile, context.kind.value, text)
            self.failed.emit(context.request_id, failure, timings)
            reply.deleteLater()
            return
        structured = parse_json_content(text)
        if not structured:
            if context.kind == QueryKind.SENTENCE and text.strip():
                structured = {"translation": text.strip(), "key_phrases": [], "learning_tip": ""}
            else:
                self.failed.emit(context.request_id, "模型返回格式无法解析", timings)
                reply.deleteLater()
                return
        self.completed.emit(context.request_id, structured, timings)
        reply.deleteLater()
