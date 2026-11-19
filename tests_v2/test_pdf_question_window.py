from PySide6.QtCore import Qt
from learning_assistant.domain.pdf_models import PdfTranslationResult
from tests_v2.test_pdf_learning_ui import setup_tab
from tests_v2.test_pdf_translate_shortcut import translation_reader, model_server


def test_alt_a_opens_nonmodal_question_window_escape_keeps_draft(qtbot, tmp_path):
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    with qtbot.waitActive(tab):
        tab.show()
        tab.activateWindow()
    tab.source.setFocus()
    qtbot.keyClick(tab.source, Qt.Key_A, Qt.AltModifier)
    popup = tab.question_window
    qtbot.waitUntil(popup.isVisible)
    assert not popup.isModal()
    assert not tab.translation_panel.isAncestorOf(tab.qa_panel.question_input)
    qtbot.waitUntil(lambda: tab.qa_panel.question_input.hasFocus() and tab.question_window.isActiveWindow())
    tab.qa_panel.question_input.setPlainText("Draft about this PDF")
    qtbot.keyClick(tab.qa_panel.question_input, Qt.Key_Escape)
    assert not popup.isVisible()
    tab.toggle_question()
    assert tab.qa_panel.question_input.toPlainText() == "Draft about this PDF"
    tab.close_session()
    assert not popup.isVisible()


def test_translation_and_question_outputs_and_clear_actions_are_independent(qtbot, tmp_path):
    tab, controller, _, _, _ = setup_tab(qtbot, tmp_path)
    controller.translation_completed.emit(PdfTranslationResult("参加讨论。", ()), False)
    tab.qa_panel.controller.started.emit("解释这句话", "Take part in the discussion.")
    tab.qa_panel.controller.completed.emit("这是邀请参加讨论。")
    assert "参加讨论。" in tab.translation.toPlainText()
    assert "解释这句话" not in tab.translation.toPlainText()
    assert "这是邀请参加讨论。" in tab.qa_panel.answer_browser.toPlainText()
    assert "翻译" not in tab.qa_panel.answer_browser.toPlainText()
    tab.qa_panel.clear_button.click()
    assert "参加讨论。" in tab.translation.toPlainText()
    assert tab.qa_panel.answer_browser.toPlainText() == ""
    tab.qa_panel.question_input.setPlainText("Keep question draft")
    tab.translation_result.clear_button.click()
    assert tab.translation.toPlainText() == ""
    assert tab.qa_panel.question_input.toPlainText() == "Keep question draft"
    tab.close_session()


def test_question_key_reload_and_popup_toggle(qtbot, tmp_path):
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    tab.settings.set("pdf_question_hotkey", "Ctrl+Shift+A")
    tab.reload_shortcuts()
    with qtbot.waitActive(tab):
        tab.show()
        tab.activateWindow()
    tab.source.setFocus()
    qtbot.keyClick(tab.source, Qt.Key_A, Qt.AltModifier)
    assert not tab.question_window.isVisible()
    with qtbot.waitActive(tab.question_window):
        qtbot.keyClick(tab.source, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
    qtbot.waitUntil(lambda: tab.qa_panel.question_input.hasFocus() and tab.question_window.isActiveWindow())
    assert tab.question_window.isVisible()
    qtbot.keyClick(tab.qa_panel.question_input, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
    assert not tab.question_window.isVisible()
    tab.close_session()


def test_question_window_expands_for_answer_and_clear_returns_to_composer(qtbot, tmp_path):
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    tab.show()
    tab.toggle_question()
    popup = tab.question_window
    compact_height = popup.height()
    assert compact_height <= 240
    tab.qa_panel.controller.started.emit("Question", "")
    tab.qa_panel.controller.completed.emit("Answer")
    qtbot.waitUntil(lambda: popup.height() > compact_height)
    assert tab.qa_panel.output_frame.isVisible()
    tab.qa_panel.clear_button.click()
    qtbot.waitUntil(lambda: popup.height() <= compact_height + 4)
    assert not tab.qa_panel.output_frame.isVisible()
    tab.close_session()


def test_switching_documents_hides_old_question_window_and_preserves_its_draft(translation_reader, qtbot, tmp_path):
    import json
    from tests_v2.test_pdf_tabs import _write_pdf
    window, first, _, server = translation_reader
    server.payload = {"choices": [{"message": {"content": "First document answer"}, "finish_reason": "stop"}]}
    first.toggle_question()
    first.qa_panel.question_input.setPlainText("First document question")
    first.qa_panel.send_button.click()
    qtbot.waitUntil(lambda: len(first.qa_panel.controller.history) == 2, timeout=8000)
    first.qa_panel.question_input.setPlainText("First document draft")
    other = tmp_path / "second.pdf"
    _write_pdf(other, "Second document evidence.")
    assert window.open_file(other)
    second = window.current_tab()
    assert not first.question_window.isVisible()
    qtbot.waitUntil(lambda: bool(second.qa_panel.controller.path), timeout=15000)
    assert second.qa_panel.controller.history == []
    second.toggle_question()
    assert second.qa_panel.question_input.toPlainText() == ""
    server.payload = {"choices": [{"message": {"content": "Second document answer"}, "finish_reason": "stop"}]}
    second.qa_panel.question_input.setPlainText("Second document question")
    second.qa_panel.send_button.click()
    qtbot.waitUntil(lambda: len(second.qa_panel.controller.history) == 2, timeout=8000)
    payload = server.requests[-1][2]
    assert "Second document evidence" in json.loads(payload["messages"][1]["content"])["pages"][0]["text"]
    assert payload["messages"][2:-1] == []
    window.tab_widget.setCurrentWidget(first)
    assert not second.question_window.isVisible()
    first.toggle_question()
    assert first.qa_panel.question_input.toPlainText() == "First document draft"
    assert "First document answer" in first.qa_panel.answer_browser.toPlainText()
