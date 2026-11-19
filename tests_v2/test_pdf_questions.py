import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import LanguageProfile, ModelProfile
from tests_v2.test_settings import SandboxedSecretStore
from tests_v2.test_model_connection import model_server
from tests_v2.test_pdfjs_view import _write_three_line_pdf


def test_question_payload_contains_every_page_and_completed_history():
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    payload = QtPdfQuestionClient.build_payload(
        ModelProfile("m", "Model", "https://api.deepseek.com/v1", "deepseek-chat", "test-key"),
        ("Beginning", "", "Final evidence"), "What supports it?",
        [{"role": "user", "content": "First question"}, {"role": "assistant", "content": "First answer"}],
        LanguageProfile(), {"text": "Highlighted sentence", "page": 3},
    )
    source = json.loads(payload["messages"][-1]["content"])
    document = json.loads(payload["messages"][1]["content"])
    assert document["pages"] == [
        {"page": 1, "text": "Beginning"}, {"page": 2, "text": ""},
        {"page": 3, "text": "Final evidence"},
    ]
    assert source["question"] == "What supports it?"
    assert source["selected_sentence"] == {"text": "Highlighted sentence", "page": 3}
    assert "pages" not in source
    assert payload["messages"][2:4] == [
        {"role": "user", "content": "First question"}, {"role": "assistant", "content": "First answer"},
    ]
    assert payload["stream"] is True
    assert payload["thinking"] == {"type": "disabled"}


def test_full_pdf_prefix_stays_identical_across_followups_and_selection_changes():
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    profile = ModelProfile("m", "Model", "https://example.test/v1", "model", "key")
    pages = ("First page", "", "Last page evidence")
    first = QtPdfQuestionClient.build_payload(profile, pages, "First question", [], LanguageProfile(),
                                               {"text": "First selection", "page": 1})
    history = [dict(first["messages"][-1]), {"role": "assistant", "content": "First answer"}]
    followup = QtPdfQuestionClient.build_payload(profile, pages, "Follow-up question", history, LanguageProfile(),
                                                  {"text": "Different selection", "page": 3})
    assert first["messages"][:2] == followup["messages"][:2]
    assert json.loads(first["messages"][1]["content"]) == {
        "pages": [{"page": 1, "text": pages[0]}, {"page": 2, "text": ""}, {"page": 3, "text": pages[2]}]}
    assert followup["messages"][2:-1] == history
    assert json.loads(followup["messages"][-1]["content"]) == {
        "question": "Follow-up question", "selected_sentence": {"text": "Different selection", "page": 3}}
    assert sum('"pages"' in message["content"] for message in followup["messages"]) == 1


def test_full_document_limits_refuse_instead_of_truncating():
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    profile = ModelProfile("m", "Model", "https://example.test/v1", "model", "key")
    with pytest.raises(ValueError, match="全文"):
        QtPdfQuestionClient.build_payload(profile, ("x" * 200_001,), "Question", [], LanguageProfile())
    with pytest.raises(ValueError, match="文字"):
        QtPdfQuestionClient.build_payload(profile, ("", " "), "Question", [], LanguageProfile())


def test_document_loader_extracts_actual_pdf_off_ui_thread(qtbot, tmp_path):
    from learning_assistant.services.pdf_document_text import PdfDocumentTextLoader
    pdf = tmp_path / "paper.pdf"
    _write_three_line_pdf(pdf)
    loader = PdfDocumentTextLoader()
    with qtbot.waitSignal(loader.loaded, timeout=8000) as signal:
        loader.load(pdf)
    assert len(signal.args[0]) == 1
    assert all(text in signal.args[0][0] for text in ("First visual line", "Second visual line", "Third visual line"))


@pytest.mark.parametrize("streaming", [False, True])
def test_question_client_uses_real_http_and_plain_answer(qtbot, qapp, model_server, streaming):
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    if streaming:
        model_server.content_type = "text/event-stream"
        model_server.response_body = b'data: {"choices":[{"delta":{"content":"Evidence [page 2]"}}]}\n\ndata: [DONE]\n\n'
    else:
        model_server.payload = {"choices": [{"message": {"content": "Evidence [page 2]"}, "finish_reason": "stop"}]}
    client = QtPdfQuestionClient(qapp)
    partial = QSignalSpy(client.partial)
    with qtbot.waitSignal(client.completed, timeout=4000) as result:
        request_id = client.start(ModelProfile("m", "Local", model_server.url, "test-model", "test-only-key"),
                                  ("First page", "Second page"), "Question?", [], LanguageProfile())
    assert result.args == [request_id, "Evidence [page 2]"]
    assert partial.count() >= 1
    assert model_server.requests[0][0] == "/v1/chat/completions"
    assert json.loads(model_server.requests[0][2]["messages"][1]["content"])["pages"][-1]["text"] == "Second page"


class FakeQuestionClient(QObject):
    partial = Signal(int, str)
    completed = Signal(int, str)
    failed = Signal(int, str)
    def __init__(self):
        super().__init__()
        self.calls = []
        self.answer_styles = []
        self.cancelled = []
    def start(self, *args, answer_style=""):
        self.calls.append(args)
        self.answer_styles.append(answer_style)
        return len(self.calls)
    def cancel(self, request_id=None):
        self.cancelled.append(request_id)


class FakeTextLoader(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    def __init__(self):
        super().__init__()
        self.paths = []
    def load(self, path, *, allow_empty=False):
        self.allow_empty = allow_empty
        self.paths.append(path)
    def cancel(self):
        pass


def make_controller(tmp_path):
    from learning_assistant.pdf_question_controller import PdfQuestionController
    from learning_assistant.services.pdf_text import document_key
    settings = SettingsStore(tmp_path / "settings.json", SandboxedSecretStore(tmp_path / "keys.json"), tmp_path / "missing.json")
    settings.upsert_model(ModelProfile("m", "Test", "https://example.test/v1", "model", "test-key"))
    path = tmp_path / "paper.pdf"
    _write_three_line_pdf(path)
    client, loader = FakeQuestionClient(), FakeTextLoader()
    controller = PdfQuestionController(settings, client=client, loader=loader)
    controller.set_document(str(path), document_key(path))
    return controller, client, loader, settings, path


def test_questions_reuse_full_text_and_only_successful_history(tmp_path):
    controller, client, loader, _, path = make_controller(tmp_path)
    controller.ask("First?", "Selected sentence", 1)
    assert not client.calls
    assert loader.paths == [path]
    loader.loaded.emit(("Page one", "Page two"))
    client.completed.emit(1, "First answer [第 2 页]")
    controller.ask("Follow-up?")
    assert len(loader.paths) == 1
    assert client.calls[1][1] == ("Page one", "Page two")
    assert client.calls[0][5] == {"text": "Selected sentence", "page": 2}
    assert json.loads(client.calls[1][3][0]["content"]) == {"question": "First?", "selected_sentence": {"text": "Selected sentence", "page": 2}}
    assert client.calls[1][3][1] == {"role": "assistant", "content": "First answer [第 2 页]"}
    controller.cancel()
    client.completed.emit(2, "Late answer")
    assert len(controller.history) == 2
    assert not controller.busy
    controller.ask("Try again?")
    assert len(client.calls[2][3]) == 2
    controller.dispose()


def test_question_close_and_changed_file_never_send_stale_text(tmp_path):
    controller, client, loader, _, path = make_controller(tmp_path)
    controller.ask("Question?")
    controller.dispose()
    loader.loaded.emit(("Late extraction",))
    assert not client.calls
    other = tmp_path / "another"
    other.mkdir()
    controller, client, loader, _, path = make_controller(other)
    path.write_bytes(path.read_bytes() + b"\nchanged")
    failure = QSignalSpy(controller.failed)
    controller.ask("Question?")
    assert not client.calls
    assert "变化" in failure.at(0)[0]


@pytest.mark.parametrize("status,body,expected", [
    (401, {"error": {"message": "unauthorized"}}, "认证"),
    (400, {"error": {"message": "maximum context length exceeded"}}, "上下文容量"),
    (429, {"error": {"message": "rate limit"}}, "额度"),
])
def test_question_http_failures_never_become_success(qtbot, qapp, model_server, status, body, expected):
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    model_server.status, model_server.payload = status, body
    client = QtPdfQuestionClient(qapp)
    completed = QSignalSpy(client.completed)
    with qtbot.waitSignal(client.failed, timeout=4000) as result:
        client.start(ModelProfile("m", "Local", model_server.url, "model", "test-only-key"),
                     ("Complete PDF text",), "Question", [], LanguageProfile())
    assert expected in result.args[1]
    assert "test-only-key" not in result.args[1]
    assert completed.count() == 0


def test_truncated_answer_is_visible_but_not_accepted(qtbot, qapp, model_server):
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    model_server.payload = {"choices": [{"message": {"content": "Partial answer"}, "finish_reason": "length"}]}
    client = QtPdfQuestionClient(qapp)
    partial, completed = QSignalSpy(client.partial), QSignalSpy(client.completed)
    with qtbot.waitSignal(client.failed, timeout=4000):
        client.start(ModelProfile("m", "Local", model_server.url, "model", "test-only-key"),
                     ("Text",), "Question", [], LanguageProfile())
    assert partial.count() == 1
    assert completed.count() == 0


def test_document_extraction_cancel_and_empty_pdf_are_reported(qtbot, tmp_path):
    from learning_assistant.services.pdf_document_text import PdfDocumentTextLoader
    from tests_v2.test_pdf_learning_ui import _write_two_pages
    pdf = tmp_path / "empty.pdf"
    _write_two_pages(pdf)
    loader = PdfDocumentTextLoader()
    with qtbot.waitSignal(loader.failed, timeout=8000) as result:
        loader.load(pdf)
    assert "文字" in result.args[0]
    document = tmp_path / "cancel.pdf"
    _write_three_line_pdf(document)
    ready = QSignalSpy(loader.loaded)
    loader.load(document)
    loader.cancel()
    # The pool is real: wait for the cancelled job to finish before checking
    # that it cannot publish stale text into the next document session.
    from PySide6.QtCore import QThreadPool, QCoreApplication
    assert QThreadPool.globalInstance().waitForDone(8000)
    QCoreApplication.processEvents()
    assert ready.count() == 0


def test_full_context_history_limit_and_no_model_do_not_send(tmp_path):
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    with pytest.raises(ValueError, match="对话"):
        QtPdfQuestionClient.build_payload(ModelProfile("m", "M", "https://example.test/v1", "m", "key"),
            ("Full PDF",), "Question", [{"role": "assistant", "content": "x" * 240_000}], LanguageProfile())
    controller, client, loader, settings, _ = make_controller(tmp_path)
    settings.set("active_model_id", "")
    failure = QSignalSpy(controller.failed)
    controller.ask("Question?")
    assert "模型" in failure.at(0)[0]
    assert not client.calls and not loader.paths
    controller.dispose()


def test_switching_document_discards_history_cache_and_inflight_answer(tmp_path):
    from learning_assistant.services.pdf_text import document_key
    controller, client, loader, _, _ = make_controller(tmp_path)
    controller.ask("First question")
    loader.loaded.emit(("First document",))
    client.completed.emit(1, "First answer")
    controller.ask("Pending follow-up")
    second = tmp_path / "second.pdf"
    _write_three_line_pdf(second)
    controller.set_document(str(second), document_key(second))
    assert client.cancelled == [2]
    assert controller.history == []
    controller.ask("Second document question")
    client.completed.emit(2, "Late first-document answer")
    assert controller.busy and controller.history == []
    assert loader.paths[-1] == second
    loader.loaded.emit(("Second document",))
    assert client.calls[-1][1] == ("Second document",)
    assert client.calls[-1][3] == []
    client.completed.emit(3, "Second answer")
    assert len(controller.history) == 2
    assert controller.history[-1]["content"] == "Second answer"
    controller.dispose()


def test_cancel_aborts_real_http_without_late_success(qtbot, qapp, model_server):
    from learning_assistant.services.pdf_questions import QtPdfQuestionClient
    model_server.delay = 0.2
    client = QtPdfQuestionClient(qapp)
    completed, failed = QSignalSpy(client.completed), QSignalSpy(client.failed)
    request_id = client.start(ModelProfile("m", "Local", model_server.url, "model", "test-only-key"),
                              ("Complete document",), "Question", [], LanguageProfile())
    qtbot.waitUntil(lambda: bool(model_server.requests), timeout=3000)
    client.cancel(request_id)
    qtbot.waitUntil(lambda: failed.count() == 1, timeout=3000)
    qtbot.wait(250)
    assert failed.at(0) == [request_id, "请求已取消"]
    assert completed.count() == 0
    assert not client._requests
