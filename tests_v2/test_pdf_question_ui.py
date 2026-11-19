from PySide6.QtCore import QUrl, Qt
from PySide6.QtTest import QSignalSpy

from learning_assistant.domain.pdf_models import PdfTextSelection
from tests_v2.test_model_connection import model_server
from tests_v2.test_pdf_questions import make_controller


def test_question_ui_sends_frozen_selection_streams_and_links_only_real_pages(qtbot, tmp_path):
    from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.resize(380, 480)
    # Wait for the native QWindow, not only QWidget's logical focus state.
    with qtbot.waitActive(panel):
        panel.show()
        panel.activateWindow()
    panel.set_selection(PdfTextSelection(1, 0, 10, "Original selected sentence"))
    panel.question_input.setPlainText("Explain the selected sentence")
    panel.question_input.setFocus()
    qtbot.waitUntil(panel.question_input.hasFocus)
    qtbot.keyClick(panel.question_input, Qt.Key_Return, Qt.ControlModifier)
    panel.set_selection(PdfTextSelection(0, 0, 10, "New selection"))
    loader.loaded.emit(("First page", "Second page"))
    assert client.calls
    assert client.calls[0][5] == {"text": "Original selected sentence", "page": 2}
    client.partial.emit(1, "First part")
    qtbot.waitUntil(lambda: "First part" in panel.answer_browser.toPlainText())
    client.completed.emit(1, 'Evidence [第 2 页]. <img src="file:///private">')
    assert '<img src="file:///private">' in panel.answer_browser.toPlainText()
    assert panel.question_input.toPlainText() == ""
    assert panel.copy_button.isEnabled()
    pages = QSignalSpy(panel.page_requested)
    panel.answer_browser.anchorClicked.emit(QUrl("pdf-page:2"))
    panel.answer_browser.anchorClicked.emit(QUrl("pdf-page:99"))
    panel.answer_browser.anchorClicked.emit(QUrl("https://example.test"))
    assert pages.count() == 1
    assert pages.at(0) == [1]
    panel.clear_button.click()
    assert controller.history == []
    assert "Evidence" not in panel.answer_browser.toPlainText()
    panel.dispose()


def test_question_failure_keeps_draft_and_stop_ignores_late_reply(qtbot, tmp_path):
    from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.question_input.setPlainText("Question to retry")
    panel.send_button.click()
    loader.loaded.emit(("PDF text",))
    client.partial.emit(1, "Partial answer")
    panel.stop_button.click()
    client.completed.emit(1, "Late answer must not appear")
    assert panel.question_input.toPlainText() == "Question to retry"
    assert "Late answer" not in panel.answer_browser.toPlainText()
    assert controller.history == []
    assert panel.send_button.isEnabled()
    panel.dispose()


def test_reader_places_only_selection_and_translation_in_sidebar(qtbot, tmp_path):
    from tests_v2.test_pdf_learning_ui import setup_tab
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    tab.resize(1100, 800)
    tab.show()
    qtbot.waitUntil(tab.isVisible)
    assert tab.translation_panel.isAncestorOf(tab.source)
    assert tab.translation_panel.isAncestorOf(tab.translation)
    assert not tab.translation_panel.isAncestorOf(tab.qa_panel.question_input)
    assert not tab.question_window.isVisible()
    assert tab.highlight_button.mapTo(tab, tab.highlight_button.rect().center()).y() < tab.source.mapTo(tab, tab.source.rect().center()).y()
    assert tab.source.mapTo(tab, tab.source.rect().center()).y() < tab.translation.mapTo(tab, tab.translation.rect().center()).y()
    assert not hasattr(tab, "copy_button")
    tab.close_session()


def test_clearing_questions_preserves_translation_phrase_learning(qtbot, tmp_path):
    from learning_assistant.domain.pdf_models import PdfPhrase, PdfTranslationResult
    from tests_v2.test_pdf_learning_ui import setup_tab
    tab, controller, repo, _, _ = setup_tab(qtbot, tmp_path)
    tab.resize(1100, 800)
    tab.show()
    qtbot.waitUntil(tab.isVisible)
    assert tab.translation is not tab.qa_panel.answer_browser
    assert not hasattr(tab.qa_panel, "selection_label")
    phrase = PdfPhrase("take part", "参加")
    controller._active_request_id = 7
    controller._on_completed(7, PdfTranslationResult("参加讨论。", (phrase,)), {})
    tab.qa_panel.controller.started.emit("这句话是什么意思？", tab.source.toPlainText())
    tab.qa_panel.controller.completed.emit("邀请读者加入讨论。")
    output = tab.qa_panel.answer_browser.toPlainText()
    assert "参加讨论。" in tab.translation.toPlainText() and "邀请读者加入讨论。" in output
    assert "Take part in the discussion." not in output
    assert tab.source.mapTo(tab, tab.source.rect().center()).y() < tab.translation.mapTo(tab, tab.translation.rect().center()).y()
    assert not tab.qa_panel.status.isVisible()
    tab.qa_panel.clear_button.click()
    assert tab.qa_panel.answer_browser.toPlainText() == ""
    assert not tab.phrase_panel.isHidden()
    tab.phrase_buttons[phrase].click()
    assert repo.due_learning_count() == 1
    tab.close_session()


def test_separate_outputs_preserve_concurrent_translation_and_question_streams(qtbot, tmp_path):
    from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    from learning_assistant.ui.pdf_translation_panel import PdfTranslationPanel
    translation = PdfTranslationPanel()
    qtbot.addWidget(translation)
    panel.question_input.setPlainText("Question")
    panel.send_button.click()
    loader.loaded.emit(("First page",))
    client.partial.emit(1, "Answer so far")
    translation.start_translation()
    translation.append_translation("Translation so far")
    qtbot.waitUntil(lambda: "Translation so far" in translation.answer_browser.toPlainText())
    qtbot.waitUntil(lambda: "Answer so far" in panel.answer_browser.toPlainText())
    assert "Answer so far" in panel.answer_browser.toPlainText()
    translation.finish_translation("Completed translation")
    client.completed.emit(1, "Completed answer")
    assert "Completed translation" in translation.answer_browser.toPlainText()
    assert "Completed translation" not in panel.answer_browser.toPlainText()
    assert "Completed answer" in panel.answer_browser.toPlainText()
    panel.set_selection(PdfTextSelection(0, 0, 8, "New text"))
    translation.clear_translation()
    assert "Completed answer" in panel.answer_browser.toPlainText()
    assert "Completed translation" not in panel.answer_browser.toPlainText()
    panel.dispose()
    translation.dispose()


def test_citation_keeps_exact_quote_in_safe_link_and_emits_location(qtbot, tmp_path):
    from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.question_input.setPlainText("Explain")
    panel.send_button.click()
    loader.loaded.emit(("First page", "Second page supporting evidence"))
    client.completed.emit(1, 'Evidence [第 2 页｜Second page supporting evidence] <img src="file:///private">')
    cursor = panel.answer_browser.document().find("[第 2 页]")
    assert not cursor.isNull()
    url = QUrl(cursor.charFormat().anchorHref())
    locations = QSignalSpy(panel.citation_requested)
    panel.answer_browser.anchorClicked.emit(url)
    assert locations.count() == 1
    assert locations.at(0) == [1, "Second page supporting evidence"]
    assert '<img src="file:///private">' in panel.answer_browser.toPlainText()
    panel.answer_browser.anchorClicked.emit(QUrl("https://example.test"))
    assert locations.count() == 1
    panel.dispose()


def test_actual_reader_extracts_whole_pdf_and_question_citation_navigates(qtbot, tmp_path, model_server):
    import json
    from PySide6.QtGui import QPainter, QPdfWriter
    from learning_assistant.core.settings import SettingsStore
    from learning_assistant.domain.models import ModelProfile
    from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
    from tests_v2.test_settings import SandboxedSecretStore
    from tests_v2.test_pdf_tabs import FakePdfController
    from tests_v2.test_pdf_render_lifecycle import _select_first_line
    from tests_v2.test_pdfjs_view import _run_javascript
    settings = SettingsStore(tmp_path / "settings.json", SandboxedSecretStore(tmp_path / "keys.json"), tmp_path / "missing.json")
    settings.upsert_model(ModelProfile("m", "Local test", model_server.url, "model", "test-only-key"))
    pdf = tmp_path / "two-pages.pdf"
    writer = QPdfWriter(str(pdf))
    painter = QPainter(writer)
    painter.drawText(100, 200, "First page selected sentence")
    writer.newPage()
    painter.drawText(100, 200, "Second page supporting evidence")
    painter.end()
    del writer
    model_server.payload = {"choices": [{"message": {"content": "Supporting evidence [第 2 页｜Second page supporting evidence]"}, "finish_reason": "stop"}]}
    window = PdfReaderWindow(settings, FakePdfController)
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    try:
        assert window.open_file(pdf)
        tab = window.current_tab()
        qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, tab.pdf_view,
            "document.querySelector('.page .textLayer span')?.getBoundingClientRect().width > 0")), timeout=15000)
        _select_first_line(qtbot, tab, tab.pdf_view)
        assert model_server.requests == []
        qa = tab.qa_panel
        tab.toggle_question()
        qa.question_input.setPlainText("Explain the selected sentence using the whole paper")
        qa.send_button.click()
        qtbot.waitUntil(lambda: "回答完成" in qa.status.text(), timeout=10000)
        source = json.loads(model_server.requests[0][2]["messages"][-1]["content"])
        document = json.loads(model_server.requests[0][2]["messages"][1]["content"])
        assert len(document["pages"]) == 2
        assert "Second page supporting evidence" in document["pages"][1]["text"]
        assert "First page selected sentence" in source["selected_sentence"]["text"]
        assert source["selected_sentence"]["page"] == 1
        assert str(pdf) not in json.dumps(model_server.requests[0][2])
        citation = qa.answer_browser.document().find("[第 2 页]")
        assert not citation.isNull()
        qa.answer_browser.anchorClicked.emit(QUrl(citation.charFormat().anchorHref()))
        assert not tab.question_window.isVisible()
        qtbot.waitUntil(lambda: _run_javascript(qtbot, tab.pdf_view,
            "PDFViewerApplication.page") == 2, timeout=5000)
        qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, tab.pdf_view,
            "Boolean(document.querySelector('.page[data-page-number=\"2\"] .linguaspark-citation'))")), timeout=5000)
        assert len(qa.controller.history) == 2
    finally:
        window.close_all_tabs()
