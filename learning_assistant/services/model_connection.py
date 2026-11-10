"""Small, cancellable chat-completions probe for the model settings form."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QByteArray, QCoreApplication, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from learning_assistant.domain.models import ModelProfile
from learning_assistant.services.ai_client import (
    QtAIClient, SSEContentParser, extract_response_content,
    chat_request_payload,
)
from learning_assistant.services.model_providers import api_endpoint


class ModelConnectionTester(QObject):
    finished = Signal(int, bool, str, int)

    def __init__(self, parent: QObject | None = None, timeout_ms: int = 12_000):
        super().__init__(parent if parent is not None else QCoreApplication.instance())
        self.network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._timeout)
        self._reply: QNetworkReply | None = None
        self._request_id = 0
        self._started = 0.0

    @staticmethod
    def validate(profile: ModelProfile, *, require_model: bool = True) -> None:
        url = QUrl(profile.base_url.strip())
        if not url.isValid() or url.scheme() not in ("https", "http") or not url.host():
            raise ValueError("请填写有效的 http:// 或 https:// 服务地址。")
        if url.hasQuery() or url.hasFragment() or url.userInfo():
            raise ValueError("服务地址不能包含查询参数、片段或账户密码。")
        if not profile.api_key.strip():
            raise ValueError("请填写 API Key。")
        if require_model and not profile.model.strip():
            raise ValueError("请填写模型 ID。")

    def start(self, profile: ModelProfile) -> int:
        self.validate(profile)
        self.cancel()
        self._profile = profile
        self._request_id += 1
        request_id = self._request_id
        request = QNetworkRequest(QUrl(api_endpoint(profile.base_url, "chat/completions")))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Authorization", f"Bearer {profile.api_key.strip()}".encode())
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.SameOriginRedirectPolicy)
        payload = chat_request_payload(
            profile, QtAIClient._provider_messages(profile, [{"role": "user", "content": "Reply with OK."}]),
            stream=False,
        )
        self._started = time.perf_counter()
        reply = self.network.post(request, QByteArray(json.dumps(payload).encode()))
        self._reply = reply
        reply.finished.connect(lambda: self._complete(reply, request_id))
        self._timer.start()
        return request_id

    def cancel(self) -> None:
        self._timer.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _elapsed(self) -> int:
        return round((time.perf_counter() - self._started) * 1000)

    def _timeout(self) -> None:
        if self._reply is None:
            return
        request_id, elapsed = self._request_id, self._elapsed()
        self.cancel()
        self.finished.emit(request_id, False, "连接超时，请检查地址和网络后重试。", elapsed)

    def _complete(self, reply: QNetworkReply, request_id: int) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        self._timer.stop()
        status = int(reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0)
        content = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()
        messages = {
            401: "认证失败，请检查 API Key。",
            403: "没有访问权限，请检查账户和模型权限。",
            404: "接口或模型不存在，请检查服务地址和模型 ID。",
            429: "请求受限或额度不足，请检查账户用量。",
        }
        if status in messages:
            success, message = False, messages[status]
        elif status >= 500:
            success, message = False, f"服务异常（HTTP {status}），请稍后重试。"
        elif error != QNetworkReply.NoError or not 200 <= status < 300:
            success, message = False, "连接失败，请检查服务地址、网络或代理设置。"
        else:
            try:
                value = json.loads(content)
                choices = value.get("choices") if isinstance(value, dict) else None
                valid_message = bool(isinstance(choices, list) and choices and isinstance(choices[0], dict)
                                     and isinstance(choices[0].get("message"), dict))
                diagnostics = SSEContentParser()
                diagnostics.observe(value)
                text = extract_response_content(value)
                failure = diagnostics.failure_message(text)
                success = valid_message and failure is None
                message = "连接成功，模型接口可用。" if success else (
                    failure if valid_message or diagnostics.api_error
                    else "服务已响应，但返回格式不符合聊天接口要求。"
                )
                if not success:
                    diagnostics.log_failure(self._profile, "probe", text)
            except (ValueError, UnicodeDecodeError):
                success = False
                message = "服务已响应，但返回格式不符合聊天接口要求。"
        self.finished.emit(request_id, success, message, self._elapsed())


class ModelCatalogFetcher(QObject):
    """Fetch IDs from the entered service without making a generation request."""

    finished = Signal(int, bool, object, str)

    def __init__(self, parent: QObject | None = None, timeout_ms: int = 12_000):
        super().__init__(parent if parent is not None else QCoreApplication.instance())
        self.network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._timeout)
        self._reply: QNetworkReply | None = None
        self._request_id = 0

    def start(self, profile: ModelProfile) -> int:
        ModelConnectionTester.validate(profile, require_model=False)
        self.cancel()
        self._request_id += 1
        request_id = self._request_id
        request = QNetworkRequest(QUrl(api_endpoint(profile.base_url, "models")))
        request.setRawHeader(b"Authorization", f"Bearer {profile.api_key.strip()}".encode())
        request.setRawHeader(b"Accept", b"application/json")
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.SameOriginRedirectPolicy)
        request.setTransferTimeout(self._timer.interval())
        reply = self.network.get(request)
        self._reply = reply
        reply.finished.connect(lambda: self._complete(reply, request_id))
        self._timer.start()
        return request_id

    def cancel(self) -> None:
        self._timer.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _timeout(self) -> None:
        if self._reply is not None:
            request_id = self._request_id
            self.cancel()
            self.finished.emit(request_id, False, [], "获取模型超时，请重试或手动填写模型 ID。")

    def _complete(self, reply: QNetworkReply, request_id: int) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        self._timer.stop()
        status = int(reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0)
        raw = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()
        messages = {
            401: "认证失败，请检查 API Key。",
            403: "没有获取模型列表的权限，可手动填写模型 ID。",
            404: "服务未提供模型列表接口，可手动填写模型 ID。",
            405: "服务未提供模型列表接口，可手动填写模型 ID。",
            429: "请求受限，请稍后刷新或手动填写模型 ID。",
        }
        models: list[str] = []
        if status in messages:
            message = messages[status]
        elif error != QNetworkReply.NoError or not 200 <= status < 300:
            message = "获取模型失败，请检查服务地址和网络，或手动填写模型 ID。"
        else:
            try:
                value = json.loads(raw)
                data = value.get("data") if isinstance(value, dict) else None
                if not isinstance(data, list):
                    message = "模型列表格式不兼容，可手动填写模型 ID。"
                else:
                    models = sorted({
                        item["id"].strip() for item in data
                        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
                    }, key=str.casefold)
                    message = f"已获取 {len(models)} 个模型，可选择或手动输入。" if models else "服务没有返回可用模型，可手动填写模型 ID。"
            except (ValueError, UnicodeDecodeError):
                message = "模型列表格式无法解析，可手动填写模型 ID。"
        self.finished.emit(request_id, bool(models), models, message)
