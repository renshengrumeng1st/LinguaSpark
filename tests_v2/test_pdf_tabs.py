from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import Qt

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.ui.pdf_reader_window import PdfReaderWindow


class FakePdfController(QObject):
    selection_changed = Signal(object)
    translation_started = Signal(str)
    translation_partial = Signal(str)
    phrase_ready = Signal(object)
    translation_completed = Signal(object, bool)
    translation_failed = Signal(str)
    annotations_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.selection = None
        self.dispose_calls = 0

    def set_selection(self, selection, _document_key: str) -> None:
        self.selection = selection

    def translate_selection(self) -> None:
        pass

    def add_highlight(self, _color: str) -> None:
        pass

    def delete_highlight(self) -> None:
        pass

    def annotations(self):
        return []

    def dispose(self) -> None:
        self.dispose_calls += 1


def _settings(tmp_path: Path) -> SettingsStore:
    return SettingsStore(
        tmp_path / "settings.json",
        secrets=SecretStore(tmp_path / "secrets.json"),
        legacy_path=tmp_path / "missing.json",
    )


def _write_pdf(path: Path, sentence: str) -> None:
    stream = f"BT /F1 18 Tf 72 720 Td ({sentence}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode())
        content.extend(value)
        content.extend(b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(content)


def test_pdf_window_opens_deduplicates_and_closes_independent_tabs(
    qtbot, tmp_path: Path
) -> None:
    first_path = tmp_path / "first.pdf"
    second_path = tmp_path / "second.pdf"
    _write_pdf(first_path, "First document.")
    _write_pdf(second_path, "Second document.")
    controllers: list[FakePdfController] = []

    def factory() -> FakePdfController:
        controller = FakePdfController()
        controllers.append(controller)
        return controller

    window = PdfReaderWindow(_settings(tmp_path), factory)
    qtbot.addWidget(window)

    assert window.tab_widget.count() == 0
    assert window.empty_state.isVisibleTo(window.content_stack)
    assert window.open_file(first_path)
    first_tab = window.current_tab()
    assert window.open_file(second_path)
    second_tab = window.current_tab()
    first_tab.translation.setPlainText("first translation")
    first_tab.pdf_view.set_zoom_factor(1.2)
    second_tab.translation.setPlainText("second translation")
    second_tab.pdf_view.set_zoom_factor(1.4)

    assert window.tab_widget.count() == 2
    assert len(controllers) == 2
    assert window.open_file(first_path)
    assert window.current_tab() is first_tab
    assert window.tab_widget.count() == 2
    assert len(controllers) == 2
    assert first_tab.translation.toPlainText() == "first translation"
    assert first_tab.pdf_view.zoomFactor() == 1.2
    assert second_tab.translation.toPlainText() == "second translation"
    assert second_tab.pdf_view.zoomFactor() == 1.4
    window.zoom_in_button.click()
    assert first_tab.pdf_view.zoomFactor() == 1.3
    assert second_tab.pdf_view.zoomFactor() == 1.4
    assert window.zoom_label.text() == "130%"

    window.close_tab(window.tab_widget.indexOf(first_tab))

    assert controllers[0].dispose_calls == 1
    assert controllers[1].dispose_calls == 0
    assert window.tab_widget.count() == 1
    assert window.current_tab() is second_tab

    window.close_tab(0)

    assert controllers[1].dispose_calls == 1
    assert window.tab_widget.count() == 0
    assert window.empty_state.isVisibleTo(window.content_stack)


def test_pdf_window_maximizes_and_focus_mode_preserves_active_tab(
    qtbot, tmp_path: Path
) -> None:
    path = tmp_path / "focus.pdf"
    _write_pdf(path, "Focused reading.")
    window = PdfReaderWindow(_settings(tmp_path), FakePdfController)
    qtbot.addWidget(window)

    assert not window.focus_button.isEnabled()
    window.show_front()
    qtbot.wait(10)
    assert window.isMaximized()
    assert window.open_file(path)
    tab = window.current_tab()
    tab.translation.setPlainText("preserved translation")
    tab.pdf_view.set_zoom_factor(1.3)

    window.focus_button.click()
    qtbot.wait(10)

    assert window.isFullScreen()
    assert window.toolbar_widget.isHidden()
    assert window.tab_widget.tabBar().isHidden()
    assert tab.isVisibleTo(window)

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    qtbot.wait(10)

    assert window.isMaximized()
    assert not window.toolbar_widget.isHidden()
    assert not window.tab_widget.tabBar().isHidden()
    assert window.current_tab() is tab
    assert tab.translation.toPlainText() == "preserved translation"
    assert tab.pdf_view.zoomFactor() == 1.3
