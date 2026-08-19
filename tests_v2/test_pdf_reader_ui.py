from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtPdfWidgets import QPdfView

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.pdf_models import (
    PdfPhrase,
    PdfTextSelection,
    PdfTranslationResult,
)
from learning_assistant.ui.pdf_reader_window import PdfReaderWindow


class FakePdfController(QObject):
    selection_changed = Signal(object)
    translation_started = Signal(str)
    translation_partial = Signal(str)
    phrase_ready = Signal(object)
    translation_completed = Signal(object, bool)
    translation_failed = Signal(str)
    annotations_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.selection = None
        self.document_key = ""
        self.translate_calls = 0
        self.highlight_colors: list[str] = []
        self.delete_calls = 0

    def set_selection(self, selection, document_key: str) -> None:
        self.selection = selection
        self.document_key = document_key

    def translate_selection(self) -> None:
        self.translate_calls += 1

    def add_highlight(self, color: str) -> None:
        self.highlight_colors.append(color)

    def delete_highlight(self) -> None:
        self.delete_calls += 1

    def annotations(self):
        return []


def _settings(tmp_path: Path, initial: dict | None = None) -> SettingsStore:
    store = SettingsStore(
        tmp_path / "settings.json",
        secrets=SecretStore(tmp_path / "secrets.json"),
        legacy_path=tmp_path / "missing.json",
    )
    if initial:
        for key, value in initial.items():
            store.set(key, value)
        store.save()
        store.load()
    return store


def _selection() -> PdfTextSelection:
    return PdfTextSelection(0, 2, 18, "A selected sentence.", ((1, 2, 30, 8),))


def test_pdf_settings_normalize_invalid_theme(tmp_path: Path) -> None:
    settings = _settings(tmp_path, {"pdf": {"theme": "neon", "last_directory": 12}})

    assert settings.get("pdf") == {"theme": "eye_care", "last_directory": ""}


def test_pdf_reader_defaults_to_eye_care_and_hides_phrase_panel(
    qtbot, tmp_path: Path
) -> None:
    window = PdfReaderWindow(FakePdfController(), _settings(tmp_path))
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.wait(10)

    assert window.theme_combo.currentData() == "eye_care"
    assert window.phrase_panel.isHidden()
    sizes = window.splitter.sizes()
    assert sizes[0] / sum(sizes) == pytest.approx(0.65, abs=0.04)


def test_translation_partial_is_visible_before_phrase_analysis(
    qtbot, tmp_path: Path
) -> None:
    controller = FakePdfController()
    window = PdfReaderWindow(controller, _settings(tmp_path))
    qtbot.addWidget(window)

    controller.translation_started.emit("A selected sentence.")
    controller.translation_partial.emit("快速译文")
    assert window.translation.toPlainText() == "快速译文"
    assert window.phrase_panel.isHidden()

    controller.phrase_ready.emit(PdfPhrase("selected sentence", "选中的句子"))
    assert not window.phrase_panel.isHidden()
    assert "selected sentence" in window.phrase_text.toPlainText()


def test_cached_completion_populates_translation_and_phrases(
    qtbot, tmp_path: Path
) -> None:
    controller = FakePdfController()
    window = PdfReaderWindow(controller, _settings(tmp_path))
    qtbot.addWidget(window)
    result = PdfTranslationResult(
        "缓存译文", (PdfPhrase("in context", "在语境中"),)
    )

    controller.translation_completed.emit(result, True)

    assert window.translation.toPlainText() == "缓存译文"
    assert "in context" in window.phrase_text.toPlainText()
    assert "缓存" in window.status.text()


def test_selection_actions_route_and_copy(qtbot, tmp_path: Path) -> None:
    controller = FakePdfController()
    window = PdfReaderWindow(controller, _settings(tmp_path))
    qtbot.addWidget(window)
    window.pdf_view.selection_changed.emit(_selection())

    assert window.has_active_selection() is True
    assert controller.selection == _selection()
    window.translate_active_selection()
    window.highlight_combo.setCurrentIndex(window.highlight_combo.findData("green"))
    window.highlight_button.click()
    window.remove_highlight_button.click()
    controller.translation_partial.emit("可复制译文")
    window.copy_button.click()

    assert controller.translate_calls == 1
    assert controller.highlight_colors == ["green"]
    assert controller.delete_calls == 1
    assert window.clipboard_text() == "可复制译文"


def test_document_load_sets_controller_identity_before_loading_marks(
    qtbot, tmp_path: Path
) -> None:
    controller = FakePdfController()
    window = PdfReaderWindow(controller, _settings(tmp_path))
    qtbot.addWidget(window)

    window.pdf_view.document_loaded.emit("document-identity", 3)

    assert controller.document_key == "document-identity"
    assert controller.selection is None


def test_theme_change_updates_view_and_persists(qtbot, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    window = PdfReaderWindow(FakePdfController(), settings)
    qtbot.addWidget(window)

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("paper"))

    assert settings.get("pdf")["theme"] == "paper"
    saved = SettingsStore(
        settings.path,
        secrets=settings.secrets,
        legacy_path=tmp_path / "missing.json",
    )
    assert saved.get("pdf")["theme"] == "paper"


def test_zoom_toolbar_adjusts_percentage_and_fits_width(qtbot, tmp_path: Path) -> None:
    window = PdfReaderWindow(FakePdfController(), _settings(tmp_path))
    qtbot.addWidget(window)

    window.zoom_in_button.click()
    assert window.pdf_view.zoomFactor() == pytest.approx(1.1)
    assert window.zoom_label.text() == "110%"

    window.zoom_out_button.click()
    assert window.pdf_view.zoomFactor() == pytest.approx(1.0)
    assert window.zoom_label.text() == "100%"

    window.fit_width_button.click()
    assert window.pdf_view.zoomMode() == QPdfView.ZoomMode.FitToWidth
