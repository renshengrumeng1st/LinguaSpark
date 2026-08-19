"""Qt-native OpenAI-compatible client with real cancellation and timings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from learning_assistant.domain.models import DictionaryEntry, ModelProfile, QueryKind, QueryRequest


PROMPT_VERSION = "learning-v2.2"


class SSEContentParser:
    """Incrementally extracts content tokens from OpenAI-style SSE frames."""

    def __init__(self):
        self.buffer = b""
        self.content: list[str] = []

    def feed(self, data: bytes) -> list[str]:
        self.buffer += data
        emitted: list[str] = []
        while b"\n" in self.buffer:
            raw, self.buffer = self.buffer.split(b"\n", 1)
            raw = raw.rstrip(b"\r")
            if not raw.startswith(b"data:"):
                continue
            payload = raw[5:].strip()
            if not payload or payload == b"[DONE]":
                continue
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            text = extract_response_content(value)
            if text:
                self.content.append(text)
                emitted.append(text)
        return emitted

    def close(self) -> list[str]:
        if not self.buffer.strip():
            return []
        return self.feed(self.buffer + b"\n")


def extract_response_content(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    choices = value.get("choices") or []
    if choices and isinstance(choices[0], dict):
        choice = choices[0]
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return str(delta["content"])
        message = choice.get("message")
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"])
        if choice.get("content"):
            return str(choice["content"])
    return str(value.get("content", "")) if value.get("content") else ""


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
        lower = profile.base_url.casefold()
        if "longcat" in lower:
            converted: list[dict[str, Any]] = []
            for message in messages:
                content = message.get("content", "")
                if not isinstance(content, list):
                    content = [{"type": "text", "text": str(content)}]
                mapped: list[dict[str, Any]] = []
                for item in content:
                    if item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        data = url.split(",", 1)[1] if "," in url else url
                        mapped.append({
                            "type": "input_image",
                            "input_image": {"type": "base64", "data": data},
                        })
                    else:
                        mapped.append(item)
                converted.append({"role": message.get("role", "user"), "content": mapped})
            return converted
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
        payload = {
            "model": profile.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
            "max_tokens": 1024,
        }
        lower_url = profile.base_url.casefold()
        if "bigmodel" in lower_url:
            # Translation/word explanation are deterministic tasks. GLM's
            # default thinking spends latency and may consume the short JSON
            # token budget before producing content.
            payload["thinking"] = {"type": "disabled"}
            payload["do_sample"] = False
            if request.kind != QueryKind.IMAGE:
                payload["response_format"] = {"type": "json_object"}
        endpoint = profile.base_url.rstrip("/") + "/chat/completions"
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
        context.parser.close()
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
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = ""
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
