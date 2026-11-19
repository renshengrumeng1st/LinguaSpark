import base64
import json

import pytest
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, QUrl, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy

from learning_assistant.domain.models import LanguageProfile, ModelProfile
from learning_assistant.services.pdf_questions import QtPdfQuestionClient
from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
from tests_v2.test_model_connection import model_server
from tests_v2.test_pdf_questions import make_controller


def screenshot():
    image = QImage(240, 120, QImage.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    image.setPixelColor(80, 60, Qt.GlobalColor.blue)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def question(qtbot, tmp_path):
    controller, client, loader, settings, path = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.show()
    yield panel, controller, client, loader, path
    panel.dispose()


def test_payload_keeps_full_pdf_prefix_and_sends_real_image_with_question():
    profile = ModelProfile("m", "Vision", "https://example.test/v1", "vision", "key")
    data = screenshot()
    plain = QtPdfQuestionClient.build_payload(profile, ("First page", "Second page"), "Explain", [], LanguageProfile())
    payload = QtPdfQuestionClient.build_payload(profile, ("First page", "Second page"), "Explain this chart", [],
                                               LanguageProfile(), {"text": "Selected claim", "page": 2}, image_bytes=data)
    assert payload["messages"][:2] == plain["messages"][:2]
    content = payload["messages"][-1]["content"]
    assert json.loads(content[0]["text"]) == {
        "question": "Explain this chart", "selected_sentence": {"text": "Selected claim", "page": 2}}
    assert content[1]["type"] == "image_url"
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == data


def test_image_snapshot_and_successful_history_survive_text_only_followup(tmp_path):
    controller, client, loader, _, _ = make_controller(tmp_path)
    data = screenshot()
    controller.ask("Explain this figure", image_bytes=data)
    loader.loaded.emit(("Complete PDF",))
    assert client.calls[0][6] == data
    client.completed.emit(1, "It shows an increasing trend.")
    controller.ask("What does the blue point mean?")
    first_user = client.calls[1][3][0]["content"]
    assert base64.b64decode(first_user[1]["image_url"]["url"].split(",", 1)[1]) == data
    controller.cancel()
    assert len(controller.history) == 2
    controller.clear()
    assert controller.history == []
    controller.dispose()


def test_paste_upload_remove_and_failure_keep_question_draft(question, qtbot, tmp_path, monkeypatch):
    panel, _, client, loader, _ = question
    panel.question_input.setPlainText("解释这张图")
    mime = QMimeData()
    mime.setImageData(QImage.fromData(screenshot()))
    panel.question_input.insertFromMimeData(mime)
    assert panel.image_bytes and panel.image_row.isVisible()
    assert panel.question_input.toPlainText() == "解释这张图"
    panel.remove_image_button.click()
    assert panel.image_bytes is None and panel.image_row.isHidden()
    path = tmp_path / "chart.png"
    path.write_bytes(screenshot())
    monkeypatch.setattr("learning_assistant.ui.pdf_question_panel.QFileDialog.getOpenFileName",
                        lambda *args, **kwargs: (str(path), ""))
    panel.upload_image_button.click()
    attached = panel.image_bytes
    assert attached
    panel.send_button.click()
    assert panel.question_input.isReadOnly()
    assert not panel.upload_image_button.isEnabled()
    assert not panel.remove_image_button.isEnabled()
    panel.question_input.insertFromMimeData(mime)
    assert panel.image_bytes == attached
    loader.loaded.emit(("Complete PDF",))
    assert client.calls[0][6] == attached
    client.failed.emit(1, "Try a vision model")
    assert panel.image_bytes == attached
    assert panel.question_input.toPlainText() == "解释这张图"
    assert panel.upload_image_button.isEnabled()
    panel.send_button.click()
    client.completed.emit(2, "This chart compares two methods.")
    assert panel.image_bytes is None and panel.image_row.isHidden()
    assert panel.question_input.toPlainText() == ""
    assert any(entry.get("image") for entry in panel._entries)
    assert '<img ' in panel.answer_browser.toHtml()


def test_image_only_question_has_default_prompt_and_clear_removes_attachment(question):
    panel, controller, client, loader, _ = question
    mime = QMimeData()
    mime.setImageData(QImage.fromData(screenshot()))
    panel.question_input.insertFromMimeData(mime)
    assert panel.send_button.isEnabled()
    panel.send_button.click()
    loader.loaded.emit(("PDF text",))
    assert client.calls[0][2].strip()
    panel.clear_button.click()
    assert panel.image_bytes is None
    assert not controller.history and not controller.busy
    assert not panel.send_button.isEnabled()


def test_corrupt_image_does_not_replace_valid_attachment_or_send(question, tmp_path):
    panel, controller, client, _, _ = question
    failures = QSignalSpy(controller.failed)
    controller.ask("Explain", image_bytes=b"not an image")
    assert failures.count() == 1 and not client.calls
    mime = QMimeData()
    mime.setImageData(QImage.fromData(screenshot()))
    panel.question_input.insertFromMimeData(mime)
    previous = panel.image_bytes
    path = tmp_path / "broken.png"
    path.write_bytes(b"broken")
    broken = QMimeData()
    broken.setUrls([QUrl.fromLocalFile(str(path))])
    panel.question_input.insertFromMimeData(broken)
    assert panel.image_bytes == previous
    assert panel.status.isVisible()


def test_uploading_non_image_does_not_insert_local_path_into_question(question, tmp_path, monkeypatch):
    panel, _, _, _, _ = question
    panel.question_input.setPlainText("保留问题草稿")
    path = tmp_path / "private-notes.txt"
    path.write_text("not an image", encoding="utf-8")
    monkeypatch.setattr("learning_assistant.ui.pdf_question_panel.QFileDialog.getOpenFileName",
                        lambda *args, **kwargs: (str(path), ""))
    panel.upload_image_button.click()
    assert panel.question_input.toPlainText() == "保留问题草稿"
    assert panel.image_bytes is None
    assert panel.status.isVisible()


def test_screenshot_question_reaches_real_http_and_vision_failure_is_clear(qtbot, qapp, model_server):
    client = QtPdfQuestionClient(qapp)
    profile = ModelProfile("m", "Local", model_server.url, "vision", "test-only-key")
    with qtbot.waitSignal(client.completed, timeout=4000):
        client.start(profile, ("Full PDF",), "Explain", [], LanguageProfile(), image_bytes=screenshot())
    assert model_server.requests[0][2]["messages"][-1]["content"][1]["type"] == "image_url"
    model_server.status = 400
    model_server.payload = {"error": {"message": "This model does not support image inputs"}}
    with qtbot.waitSignal(client.failed, timeout=4000) as failure:
        client.start(profile, ("Full PDF",), "Explain", [], LanguageProfile(), image_bytes=screenshot())
    assert "图片" in failure.args[1] and "模型" in failure.args[1]
    assert "test-only-key" not in failure.args[1]


def test_image_limits_do_not_count_base64_as_text_or_drop_screenshots(monkeypatch):
    from learning_assistant.services import pdf_questions, pdf_question_images
    data = screenshot()
    profile = ModelProfile("m", "Vision", "https://example.test/v1", "vision", "key")
    first = QtPdfQuestionClient.build_payload(profile, ("Full PDF",), "Explain", [], LanguageProfile(), image_bytes=data)
    history = [first["messages"][-1], {"role": "assistant", "content": "Chart explanation"}]
    second = QtPdfQuestionClient.build_payload(profile, ("Full PDF",), "Follow-up", history, LanguageProfile())
    assert first["messages"][:2] == second["messages"][:2]
    assert second["messages"][2]["content"][1] == history[0]["content"][1]
    text_size = sum(pdf_question_images.content_sizes(item["content"])[0] for item in first["messages"])
    monkeypatch.setattr(pdf_questions, "MAX_CONTEXT_CHARS", text_size + 1)
    assert QtPdfQuestionClient.build_payload(profile, ("Full PDF",), "Explain", [], LanguageProfile(), image_bytes=data)
    monkeypatch.setattr(pdf_questions, "MAX_CONTEXT_IMAGE_BYTES", len(data) - 1)
    with pytest.raises(ValueError, match="截图"):
        QtPdfQuestionClient.build_payload(profile, ("Full PDF",), "Explain", [], LanguageProfile(), image_bytes=data)
    with pytest.raises(ValueError, match="8 MB"):
        pdf_question_images.image_part(data + bytes(pdf_question_images.MAX_IMAGE_BYTES))


def test_scanned_pdf_can_be_explained_from_screenshot_but_not_invented_text(qtbot, tmp_path):
    from learning_assistant.services.pdf_document_text import PdfDocumentTextLoader
    from tests_v2.test_pdf_learning_ui import _write_two_pages
    path = tmp_path / "scanned.pdf"
    _write_two_pages(path)
    loader = PdfDocumentTextLoader()
    with qtbot.waitSignal(loader.loaded, timeout=8000) as loaded:
        loader.load(path, allow_empty=True)
    pages = loaded.args[0]
    assert len(pages) == 2 and not any(pages)
    profile = ModelProfile("m", "Vision", "https://example.test/v1", "vision", "key")
    first = QtPdfQuestionClient.build_payload(profile, pages, "Explain", [], LanguageProfile(), image_bytes=screenshot())
    history = [first["messages"][-1], {"role": "assistant", "content": "Screenshot explanation"}]
    assert QtPdfQuestionClient.build_payload(profile, pages, "Follow-up", history, LanguageProfile())
    with pytest.raises(ValueError, match="文字"):
        QtPdfQuestionClient.build_payload(profile, pages, "Explain", [], LanguageProfile())


def test_paste_shortcut_and_hidden_window_keep_screenshot_draft(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication
    from tests_v2.test_pdf_learning_ui import setup_tab
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    with qtbot.waitActive(tab):
        tab.show()
        tab.activateWindow()
    try:
        tab.toggle_question()
        panel = tab.qa_panel
        qtbot.waitUntil(lambda: panel.question_input.hasFocus() and tab.question_window.isActiveWindow())
        QApplication.clipboard().setImage(QImage.fromData(screenshot()))
        qtbot.keyClick(panel.question_input, Qt.Key_V, Qt.ControlModifier)
        assert panel.image_bytes
        assert panel.image_row.isVisible()
        assert tab.question_window.height() >= 260
        draft = panel.image_bytes
        qtbot.keyClick(panel.question_input, Qt.Key_Escape)
        assert not tab.question_window.isVisible()
        tab.toggle_question()
        assert panel.image_bytes == draft
        panel.clear_button.click()
        assert panel.image_bytes is None
        assert tab.question_window.height() <= 240
    finally:
        tab.close_session()
