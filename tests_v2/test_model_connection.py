"""Exercise the real Qt HTTP boundary without contacting a model provider."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest
from PySide6.QtTest import QSignalSpy

from learning_assistant.domain.models import ModelProfile
from learning_assistant.services.model_connection import ModelConnectionTester


@pytest.fixture
def model_server():
    class State:
        status = 200
        payload = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        delay = 0
        requests = []
        response_body = None
        content_type = "application/json"

    state = State()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append((self.path, self.headers.get("Authorization"), None))
            time.sleep(state.delay)
            content = json.dumps(state.payload).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.path, self.headers.get("Authorization"), body))
            time.sleep(state.delay)
            content = state.response_body if state.response_body is not None else json.dumps(state.payload).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", state.content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def profile(server):
    return ModelProfile("test", "Local test", server.url, "test-model", "test-only-key")


def test_connection_posts_to_chat_endpoint_with_selected_model(qtbot, model_server):
    tester = ModelConnectionTester()
    with qtbot.waitSignal(tester.finished, timeout=2500) as signal:
        request_id = tester.start(profile(model_server))
    assert signal.args[0:2] == [request_id, True]
    assert signal.args[3] >= 0
    path, authorization, body = model_server.requests[0]
    assert path == "/v1/chat/completions"
    assert authorization == "Bearer test-only-key"
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": "Reply with OK."}]


@pytest.mark.parametrize("status,expected", [
    (401, "认证失败"), (403, "权限"), (404, "接口或模型"),
    (429, "额度"), (503, "服务异常"),
])
def test_http_error_has_actionable_feedback(qtbot, model_server, status, expected):
    model_server.status = status
    tester = ModelConnectionTester()
    with qtbot.waitSignal(tester.finished, timeout=2500) as signal:
        tester.start(profile(model_server))
    assert signal.args[1] is False
    assert expected in signal.args[2]
    assert "test-only-key" not in signal.args[2]


def test_success_requires_a_chat_completion_response(qtbot, model_server):
    model_server.payload = {"status": "ok"}
    tester = ModelConnectionTester()
    with qtbot.waitSignal(tester.finished, timeout=2500) as signal:
        tester.start(profile(model_server))
    assert signal.args[1] is False
    assert "格式" in signal.args[2]


def test_reasoning_only_truncated_response_is_not_a_success(qtbot, model_server):
    model_server.payload = {"choices": [{"message": {"content": None, "reasoning_content": "thinking"}, "finish_reason": "length"}]}
    tester = ModelConnectionTester()
    with qtbot.waitSignal(tester.finished, timeout=2500) as signal:
        tester.start(profile(model_server))
    assert signal.args[1] is False
    assert "截断" in signal.args[2]


def test_timeout_and_cancel_do_not_emit_late_success(qtbot, model_server):
    model_server.delay = 0.25
    tester = ModelConnectionTester(timeout_ms=80)
    results = QSignalSpy(tester.finished)
    tester.start(profile(model_server))
    qtbot.waitUntil(lambda: results.count() == 1, timeout=2000)
    assert results.at(0)[1] is False
    assert "超时" in results.at(0)[2]
    tester.start(profile(model_server))
    tester.cancel()
    qtbot.wait(300)
    assert results.count() == 1


@pytest.mark.parametrize("base_url", ["not a url", "ftp://example.com", "https://"])
def test_invalid_endpoint_is_rejected_before_network(qtbot, base_url):
    tester = ModelConnectionTester()
    with pytest.raises(ValueError, match="地址"):
        tester.start(ModelProfile("test", "Test", base_url, "test-model", "test-only-key"))


def test_discovery_reads_authenticated_models_without_a_model_id(qtbot, model_server):
    from learning_assistant.services.model_connection import ModelCatalogFetcher
    model_server.payload = {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "z-model"}, {"id": None}, "bad"]}
    fetcher = ModelCatalogFetcher()
    with qtbot.waitSignal(fetcher.finished, timeout=2500) as signal:
        request_id = fetcher.start(ModelProfile("", "", model_server.url, "", "catalog-key"))
    assert signal.args[:3] == [request_id, True, ["a-model", "z-model"]]
    assert model_server.requests == [("/v1/models", "Bearer catalog-key", None)]


@pytest.mark.parametrize("status,payload,expected", [
    (401, {}, "认证"), (404, {}, "手动"),
    (200, {"status": "ok"}, "格式"), (200, {"data": []}, "模型"),
])
def test_catalog_failure_keeps_manual_configuration_available(qtbot, model_server, status, payload, expected):
    from learning_assistant.services.model_connection import ModelCatalogFetcher
    model_server.status, model_server.payload = status, payload
    fetcher = ModelCatalogFetcher()
    with qtbot.waitSignal(fetcher.finished, timeout=2500) as signal:
        fetcher.start(profile(model_server))
    assert signal.args[1:3] == [False, []]
    assert expected in signal.args[3]


def test_catalog_timeout_and_cancel_ignore_late_results(qtbot, model_server):
    from learning_assistant.services.model_connection import ModelCatalogFetcher
    model_server.delay = 0.2
    model_server.payload = {"data": [{"id": "old-model"}]}
    fetcher = ModelCatalogFetcher(timeout_ms=60)
    spy = QSignalSpy(fetcher.finished)
    fetcher.start(profile(model_server))
    qtbot.waitUntil(lambda: spy.count() == 1)
    assert spy.at(0)[1] is False
    assert "超时" in spy.at(0)[3]
    fetcher.start(profile(model_server))
    fetcher.cancel()
    qtbot.wait(300)
    assert spy.count() == 1


def test_discovery_validation_never_requires_a_model_id(qtbot):
    from learning_assistant.services.model_connection import ModelCatalogFetcher
    fetcher = ModelCatalogFetcher()
    with pytest.raises(ValueError) as error:
        fetcher.start(ModelProfile("", "", "https://example.com/v1", "", ""))
    assert "API Key" in str(error.value)
    assert "模型 ID" not in str(error.value)
