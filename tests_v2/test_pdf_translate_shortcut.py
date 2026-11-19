import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import ModelProfile
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.services.pdf_translation import QtPdfTranslationClient
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
from tests_v2.test_model_connection import model_server
from tests_v2.test_settings import SandboxedSecretStore
from tests_v2.test_pdfjs_view import _write_three_line_pdf, _run_javascript
from tests_v2.test_pdf_render_lifecycle import _select_first_line


@pytest.fixture
def translation_reader(qtbot, qapp, tmp_path, model_server):
    settings = SettingsStore(tmp_path / "settings.json", SandboxedSecretStore(tmp_path / "keys.json"), tmp_path / "missing.json")
    settings.upsert_model(ModelProfile("m", "Local", model_server.url, "model", "test-only-key"))
    settings.set("selection_hotkey", "<Alt-W>")
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    client = QtPdfTranslationClient(qapp)
    model_server.payload = {"choices": [{"message": {"content": "第一行可见文字。\n<<<PHRASES>>>\nvisual line || 可见行"}, "finish_reason": "stop"}]}
    window = PdfReaderWindow(settings, lambda: PdfTranslationController(settings, repository, client))
    qtbot.addWidget(window)
    pdf = tmp_path / "shortcuts.pdf"
    _write_three_line_pdf(pdf)
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()
    try:
        assert window.open_file(pdf)
        tab = window.current_tab()
        qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, tab.pdf_view,
            "document.querySelector('.page .textLayer span')?.getBoundingClientRect().width > 0")), timeout=15000)
        _select_first_line(qtbot, tab, tab.pdf_view)
        yield window, tab, settings, model_server
    finally:
        window.close_all_tabs()


@pytest.mark.parametrize("focus", ["pdf", "source", "output", "question"])
def test_alt_w_translates_committed_pdf_selection_from_reader_children(translation_reader, qtbot, focus):
    _, tab, _, server = translation_reader
    target = {"pdf": tab.pdf_view, "source": tab.source,
              "output": tab.translation, "question": tab.qa_panel.question_input}[focus]
    tab.qa_panel.question_input.setPlainText("Question draft stays here")
    if focus == "question":
        tab.toggle_question()
        qtbot.waitUntil(tab.question_window.isActiveWindow)
    target.setFocus()
    qtbot.waitUntil(target.hasFocus)
    started = QSignalSpy(tab.controller.translation_started)
    qtbot.keyClick(target.focusProxy() or target, Qt.Key_W, Qt.AltModifier)
    assert started.count() == 1
    qtbot.waitUntil(lambda: "第一行可见文字。" in tab.translation.toPlainText(), timeout=5000)
    assert len(server.requests) == 1
    assert "First visual line" in server.requests[0][2]["messages"][-1]["content"]
    assert tab.qa_panel.question_input.toPlainText() == "Question draft stays here"


def test_translation_shortcut_reloads_setting_and_ignores_empty_selection(translation_reader, qtbot):
    window, tab, settings, server = translation_reader
    settings.set("selection_hotkey", "Ctrl+J")
    window.reload_shortcuts()
    tab.source.setFocus()
    qtbot.waitUntil(tab.source.hasFocus)
    qtbot.keyClick(tab.source, Qt.Key_W, Qt.AltModifier)
    assert server.requests == []
    assert "Ctrl+J" in tab.translate_button.toolTip()
    qtbot.keyClick(tab.source, Qt.Key_J, Qt.ControlModifier)
    qtbot.waitUntil(lambda: "第一行可见文字。" in tab.translation.toPlainText(), timeout=5000)
    started = QSignalSpy(tab.controller.translation_started)
    tab.pdf_view.clear_selection()
    qtbot.keyClick(tab.source, Qt.Key_J, Qt.ControlModifier)
    assert started.count() == 0
    assert len(server.requests) == 1


def test_translation_shortcut_only_runs_for_current_document(translation_reader, qtbot, tmp_path):
    window, first, _, server = translation_reader
    other_pdf = tmp_path / "other.pdf"
    _write_three_line_pdf(other_pdf)
    assert window.open_file(other_pdf)
    second = window.current_tab()
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, second.pdf_view,
        "document.querySelector('.page .textLayer span')?.getBoundingClientRect().width > 0")), timeout=15000)
    _select_first_line(qtbot, second, second.pdf_view)
    second.pdf_view.setFocus()
    qtbot.waitUntil(second.pdf_view.hasFocus)
    first_started = QSignalSpy(first.controller.translation_started)
    second_started = QSignalSpy(second.controller.translation_started)
    qtbot.keyClick(second.pdf_view.focusProxy() or second.pdf_view, Qt.Key_W, Qt.AltModifier)
    assert first_started.count() == 0
    assert second_started.count() == 1
    qtbot.waitUntil(lambda: "第一行可见文字。" in second.translation.toPlainText(), timeout=5000)
    assert first.translation.toPlainText() == ""
    assert len(server.requests) == 1
