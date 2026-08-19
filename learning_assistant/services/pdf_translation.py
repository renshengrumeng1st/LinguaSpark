"""Low-latency OpenAI-compatible streaming client for PDF selections."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from learning_assistant.domain.models import LanguageProfile, ModelProfile
from learning_assistant.services.ai_client import (
    QtAIClient,
    SSEContentParser,
    extract_response_content,
)
from learning_assistant.services.pdf_text import PdfTranslationStreamParser


PDF_PROMPT_VERSION = "pdf-selection-v1.0"


@dataclass(slots=True)
class PdfRequestContext:
    request_id: int
    profile: ModelProfile
    sse: SSEContentParser
    content: PdfTranslationStreamParser
    started_at: float
    first_byte_at: float | None = None
    raw: bytearray | None = None


class QtPdfTranslationClient(QObject):
    translation_partial = Signal(int, str)
    phrase_ready = Signal(int, object)
    completed = Signal(int, object, object)
    failed = Signal(int, str, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.network.setTransferTimeout(35_000)
        self._next_id = 0
        self._requests: dict[QNetworkReply, PdfRequestContext] = {}

    @staticmethod
    def build_payload(
        profile: ModelProfile,
        text: str,
        languages: LanguageProfile,
    ) -> dict:
        system = (
            "You are a fast, precise translation assistant. Output the natural target-language "
            "translation first, with no label or commentary. After the translation, output the "
            "exact delimiter <<<PHRASES>>> on its own line. Then output at most 5 genuinely useful "
            "phrases, one per line, as: source phrase || target-language meaning. Do not add grammar "
            "lessons, headings, numbering, paths, or any other content."
        )
        user = json.dumps(
            {
                "task": "translate_pdf_selection",
                "text": text,
                "source_language": languages.source,
                "target_language": languages.target,
            },
            ensure_ascii=False,
        )
        messages = QtAIClient._provider_messages(
            profile,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        payload: dict = {
            "model": profile.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
            "max_tokens": 768,
        }
        if "bigmodel" in profile.base_url.casefold():
            payload["thinking"] = {"type": "disabled"}
            payload["do_sample"] = False
        return payload

    def start(
        self,
        profile: ModelProfile,
        text: str,
        languages: LanguageProfile,
    ) -> int:
        self._next_id += 1
        request_id = self._next_id
        payload = self.build_payload(profile, text, languages)
        request = QNetworkRequest(
            QUrl(profile.base_url.rstrip("/") + "/chat/completions")
        )
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"text/event-stream, application/json")
        request.setRawHeader(
            b"Authorization", QByteArray(f"Bearer {profile.api_key}".encode("utf-8"))
        )
        request.setTransferTimeout(35_000)
        reply = self.network.post(
            request,
            QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        )
        self._requests[reply] = PdfRequestContext(
            request_id=request_id,
            profile=profile,
            sse=SSEContentParser(),
            content=PdfTranslationStreamParser(),
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

    def _feed_tokens(self, context: PdfRequestContext, tokens: list[str]) -> None:
        for token in tokens:
            update = context.content.feed(token)
            if update.translation_delta:
                self.translation_partial.emit(
                    context.request_id, update.translation_delta
                )
            for phrase in update.phrases:
                self.phrase_ready.emit(context.request_id, phrase)

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
        self._feed_tokens(context, context.sse.feed(data))

    @staticmethod
    def _timings(context: PdfRequestContext) -> dict[str, int | None]:
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
        self._feed_tokens(context, context.sse.close())
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

        if not context.sse.content:
            try:
                response = json.loads(bytes(context.raw or b"{}"))
                text = extract_response_content(response)
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = ""
            if text:
                self._feed_tokens(context, [text])
        result = context.content.close()
        if not result.translation:
            self.failed.emit(context.request_id, "模型没有返回译文", timings)
        else:
            self.completed.emit(context.request_id, result, timings)
        reply.deleteLater()
