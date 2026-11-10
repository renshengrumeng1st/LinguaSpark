from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QTabWidget

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.pdf_models import PdfPhrase, PdfTextSelection, PdfTranslationResult
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.services.pdf_text import document_key
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.pdf_reader_tab import PdfReaderTab
from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
from tests_v2.test_pdf_translation import FakePdfClient
from tests_v2.test_pdf_tabs import _write_pdf


def setup_tab(qtbot, tmp_path):
    settings = SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"), tmp_path / "missing.json")
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    controller = PdfTranslationController(settings, repo, FakePdfClient())
    tab = PdfReaderTab(controller, settings)
    qtbot.addWidget(tab)
    pdf = tmp_path / "source.pdf"
    _write_pdf(pdf, "Take part in the discussion.")
    tab.document_path = str(pdf)
    selection = PdfTextSelection(0, 0, 28, "Take part in the discussion.")
    controller.set_selection(selection, document_key(pdf))
    return tab, controller, repo, pdf, selection


def test_phrase_add_is_enabled_only_after_completion_and_updates_review_queue(qtbot, tmp_path):
    tab, controller, repo, _, selection = setup_tab(qtbot, tmp_path)
    phrase = PdfPhrase("take part", "参加")
    controller.translation_started.emit(selection.text)
    controller.phrase_ready.emit(phrase)
    assert not tab.phrase_buttons[phrase].isEnabled()
    controller._active_request_id = 7
    controller._on_completed(7, PdfTranslationResult("参加讨论。", (phrase,)), {})
    button = tab.phrase_buttons[phrase]
    assert button.isEnabled()
    button.click()
    assert repo.due_learning_count() == 1
    assert button.text() == "已加入学习"
    assert not button.isEnabled()
    assert repo.due_learning_items()[0].context == selection.text


def test_changing_selection_clears_old_learning_actions(qtbot, tmp_path):
    tab, controller, repo, pdf, selection = setup_tab(qtbot, tmp_path)
    phrase = PdfPhrase("take part", "参加")
    controller._active_request_id = 7
    controller._on_completed(7, PdfTranslationResult("参加讨论。", (phrase,)), {})
    assert tab.phrase_buttons[phrase].isEnabled()
    controller.set_selection(PdfTextSelection(0, 30, 45, "Another phrase."), document_key(pdf))
    assert tab.phrase_panel.isHidden()
    assert not tab.phrase_buttons
    assert repo.due_learning_count() == 0


def test_highlight_color_picker_opens_without_a_text_selection(qtbot, tmp_path):
    tab, controller, _, pdf, selection = setup_tab(qtbot, tmp_path)
    controller.set_selection(None, document_key(pdf))
    tab.resize(1100, 700)
    tab.show()
    tab.activateWindow()
    qtbot.waitUntil(lambda: tab.isActiveWindow())
    assert tab.highlight_combo.isEnabled()
    assert not tab.highlight_button.isEnabled()
    qtbot.mouseClick(tab.highlight_combo, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.highlight_combo.view().isVisible())
    qtbot.keyClick(tab.highlight_combo.view(), Qt.Key_Down)
    qtbot.keyClick(tab.highlight_combo.view(), Qt.Key_Return)
    assert tab.highlight_combo.currentData() == "green"
    assert controller.annotations() == []
    controller.set_selection(selection, document_key(pdf))
    tab.highlight_button.click()
    assert controller.annotations()[0].color == "green"
    tab.close_session()


def test_highlight_shortcuts_follow_active_tab_and_selection(qtbot, tmp_path):
    tab, controller, _, pdf, selection = setup_tab(qtbot, tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other, other_controller, _, _, _ = setup_tab(qtbot, other_dir)
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(tab, "First")
    tabs.addTab(other, "Second")
    tabs.show()
    tabs.activateWindow()
    tab.pdf_view.setFocus()
    qtbot.waitUntil(lambda: tab.pdf_view.hasFocus())
    key_target = tab.pdf_view.focusProxy() or tab.pdf_view
    tab.highlight_combo.setCurrentIndex(2)
    modifiers = Qt.KeyboardModifier.ControlModifier
    qtbot.keyClick(key_target, Qt.Key.Key_H, modifiers)
    assert len(controller.annotations()) == 1
    assert controller.annotations()[0].color == "pink"
    assert other_controller.annotations() == []
    qtbot.keyClick(key_target, Qt.Key.Key_R, modifiers)
    assert controller.annotations() == []
    tabs.setCurrentWidget(other)
    other.source.setFocus()
    qtbot.keyClick(other.source, Qt.Key.Key_H, modifiers)
    assert len(other_controller.annotations()) == 1
    assert controller.annotations() == []
    tabs.setCurrentWidget(tab)
    tab.source.setFocus()
    controller.set_selection(PdfTextSelection(0, -1, -1, selection.text, can_annotate=False), document_key(pdf))
    qtbot.keyClick(tab.source, Qt.Key.Key_H, modifiers)
    assert controller.annotations() == []
    controller.set_selection(None, document_key(pdf))
    qtbot.keyClick(tab.source, Qt.Key.Key_H, modifiers)
    assert controller.annotations() == []
    tab.close_session()
    other.close_session()


def test_saved_pdf_hotkeys_reload_open_tabs_when_settings_close(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from learning_assistant.application import LearningAssistantApplication
    from learning_assistant.services.selection import GlobalHotkeyService

    tab, controller, _, _, _ = setup_tab(qtbot, tmp_path)
    window = PdfReaderWindow(controller.settings, lambda: controller)
    qtbot.addWidget(window)
    window.tab_widget.addTab(tab, "Open PDF")
    window._sync_empty_state()
    window.show()
    window.activateWindow()
    tab.source.setFocus()
    qtbot.waitUntil(lambda: tab.source.hasFocus())
    # Only the OS-wide registration boundary is replaced; PDF shortcuts are real.
    monkeypatch.setattr(GlobalHotkeyService, "start", lambda self: None)
    monkeypatch.setattr(GlobalHotkeyService, "stop", lambda self: None)
    app = LearningAssistantApplication.__new__(LearningAssistantApplication)
    app.settings = controller.settings
    app.hotkeys = GlobalHotkeyService({})
    app.mode_router = SimpleNamespace(pdf_window=window)
    app.tray = SimpleNamespace(setToolTip=lambda text: None)
    app.settings.set("pdf_highlight_hotkey", "Ctrl+K")
    app.settings.set("pdf_remove_highlight_hotkey", "Ctrl+M")
    app._reload_hotkeys()
    qtbot.keyClick(tab.source, Qt.Key_H, Qt.ControlModifier)
    assert controller.annotations() == []
    qtbot.keyClick(tab.source, Qt.Key_K, Qt.ControlModifier)
    assert len(controller.annotations()) == 1
    assert "Ctrl+K" in tab.highlight_button.toolTip()
    qtbot.keyClick(tab.source, Qt.Key_R, Qt.ControlModifier)
    assert len(controller.annotations()) == 1
    qtbot.keyClick(tab.source, Qt.Key_M, Qt.ControlModifier)
    assert controller.annotations() == []
    assert "Ctrl+M" in tab.remove_highlight_button.toolTip()
    app.hotkeys.triggered.disconnect()
    app.hotkeys.registration_failed.disconnect()
    app.hotkeys.deleteLater()
    tab.close_session()


def test_learning_save_failure_can_retry_without_regenerating_translation(qtbot, tmp_path, monkeypatch):
    tab, controller, repo, _, _ = setup_tab(qtbot, tmp_path)
    phrase = PdfPhrase("take part", "参加")
    controller._active_request_id = 7
    controller._on_completed(7, PdfTranslationResult("参加讨论。", (phrase,)), {})
    original = repo.add_learning_item
    def fail_write(*args, **kwargs):
        raise OSError("temporary write failure")
    monkeypatch.setattr(repo, "add_learning_item", fail_write)
    tab.phrase_buttons[phrase].click()
    assert "保存" in tab.status.text()
    assert tab.phrase_buttons[phrase].isEnabled()
    monkeypatch.setattr(repo, "add_learning_item", original)
    tab.phrase_buttons[phrase].click()
    assert repo.due_learning_count() == 1
    assert not controller.client.start_calls


def test_reader_reuses_open_tab_when_returning_to_source(qtbot, tmp_path):
    tab, controller, repo, pdf, _ = setup_tab(qtbot, tmp_path)
    window = PdfReaderWindow(controller.settings, lambda: PdfTranslationController(controller.settings, repo, FakePdfClient()))
    qtbot.addWidget(window)
    assert window.open_file(pdf)
    original_tab = window.current_tab()
    assert window.open_source({"path": str(pdf), "page_index": 0})
    assert window.current_tab() is original_tab
    assert window.tab_widget.count() == 1
    assert not window.open_source({"path": str(tmp_path / "missing.pdf"), "page_index": 0})
    assert window.tab_widget.count() == 1
    window.close_all_tabs()


def test_pdf_reader_exposes_review_entry_without_creating_network_request(qtbot, tmp_path):
    tab, controller, _, _, _ = setup_tab(qtbot, tmp_path)
    window = PdfReaderWindow(controller.settings, lambda: controller)
    qtbot.addWidget(window)
    spy = QSignalSpy(window.review_requested)
    window.review_button.click()
    assert spy.count() == 1
    assert not controller.client.start_calls


def test_review_returns_to_pdf_through_application_wiring(qtbot, tmp_path):
    from types import SimpleNamespace
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication
    from learning_assistant.application import LearningAssistantApplication, ApplicationModeRouter
    from learning_assistant.controller import LearningController
    from tests_v2.test_convenience import Dictionary, AI
    from tests_v2.test_ui_smoke import FakeSpeech
    from tests_v2.test_settings_models import ReadOnlyAutostart
    _, source_controller, repo, pdf, selection = setup_tab(qtbot, tmp_path)
    phrase = PdfPhrase("take part", "参加")
    source_controller._active_request_id = 5
    source_controller._on_completed(5, PdfTranslationResult("参加讨论。", (phrase,)), {})
    assert source_controller.add_phrase_to_learning(phrase, str(pdf))
    app = LearningAssistantApplication.__new__(LearningAssistantApplication)
    app.qt = QApplication.instance()
    app.settings = source_controller.settings
    app.repository = repo
    app.controller = LearningController(app.settings, Dictionary(), repo, AI())
    app.speech = FakeSpeech()
    app.autostart = ReadOnlyAutostart()
    app.main_window = None
    app.pdf_client = None
    app.hotkeys = SimpleNamespace(stop=lambda: None)
    app.review_action = QAction()
    app.mode_router = ApplicationModeRouter(app._create_compact_window, app._create_pdf_window)
    qtbot.addWidget(app.mode_router.chooser)
    reader = app.mode_router.show_pdf()
    qtbot.addWidget(reader)
    reader.review_button.click()
    main = app.main_window
    qtbot.addWidget(main)
    review = main._review_dialog
    assert review.isVisible()
    review.pdf_source_button.click()
    assert reader.current_tab().document_path == str(pdf.resolve())
    assert not review.isVisible()
    app._learning_changed()
    assert main.review_button.text() == "复习 1"
    assert "1" in app.review_action.text()
    reader.close_all_tabs()


def _write_two_pages(path: Path):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects)+1}\n".encode() + b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(content)


def test_pdf_navigation_queued_before_ready_reaches_requested_page(qtbot, tmp_path):
    from learning_assistant.ui.pdfjs_view import PdfJsViewAdapter
    from tests_v2.test_pdfjs_view import _run_javascript
    pdf = tmp_path / "two-pages.pdf"
    _write_two_pages(pdf)
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    try:
        assert view.load_file(pdf)
        assert view.go_to_page(1)
        qtbot.waitUntil(lambda: _run_javascript(qtbot, view, "globalThis.PDFViewerApplication?.page || 0") == 2, timeout=15000)
        assert view.go_to_page(999)
        assert not view.go_to_page(-1)
        assert _run_javascript(qtbot, view, "globalThis.PDFViewerApplication.page") == 2
        view.close_document()
        assert view.load_file(pdf)
        qtbot.waitUntil(lambda: _run_javascript(qtbot, view, "globalThis.PDFViewerApplication?.page || 0") == 1, timeout=15000)
    finally:
        view.close_document()
