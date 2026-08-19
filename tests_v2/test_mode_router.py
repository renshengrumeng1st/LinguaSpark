from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

from learning_assistant.application import (
    ApplicationModeRouter,
    LearningAssistantApplication,
)


class FakeWindow(QWidget):
    def __init__(self, active_selection: bool = False):
        super().__init__()
        self.active_selection = active_selection
        self.front_calls = 0
        self.translate_calls = 0

    def show_front(self) -> None:
        self.front_calls += 1
        self.show()

    def has_active_selection(self) -> bool:
        return self.active_selection

    def translate_active_selection(self) -> None:
        self.translate_calls += 1


class FakeSelectionService:
    def __init__(self):
        self.request_calls = 0

    def request(self) -> None:
        self.request_calls += 1


def test_mode_router_starts_with_only_chooser_and_creates_modes_lazily(qtbot):
    compact_created: list[FakeWindow] = []
    pdf_created: list[FakeWindow] = []

    def create_compact():
        compact_created.append(FakeWindow())
        return compact_created[-1]

    def create_pdf():
        pdf_created.append(FakeWindow())
        return pdf_created[-1]

    router = ApplicationModeRouter(create_compact, create_pdf)
    qtbot.addWidget(router.chooser)

    router.show_chooser()

    assert router.chooser.isVisible()
    assert router.compact_window is None
    assert router.pdf_window is None

    router.chooser.compact_requested.emit()
    assert len(compact_created) == 1
    assert compact_created[0].isVisible()
    assert not router.chooser.isVisible()

    router.show_pdf()
    assert len(pdf_created) == 1
    assert pdf_created[0].isVisible()
    assert not compact_created[0].isVisible()

    router.show_pdf()
    assert len(pdf_created) == 1
    assert pdf_created[0].front_calls == 2


def test_alt_w_prefers_visible_pdf_selection(qtbot):
    pdf_window = FakeWindow(active_selection=True)
    qtbot.addWidget(pdf_window)
    pdf_window.show()
    selection = FakeSelectionService()
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.mode_router = SimpleNamespace(pdf_window=pdf_window)
    application.selection = selection

    application._hotkey("selection")

    assert pdf_window.translate_calls == 1
    assert selection.request_calls == 0


def test_alt_w_falls_back_without_visible_pdf_selection(qtbot):
    pdf_window = FakeWindow(active_selection=False)
    qtbot.addWidget(pdf_window)
    pdf_window.show()
    selection = FakeSelectionService()
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.mode_router = SimpleNamespace(pdf_window=pdf_window)
    application.selection = selection

    application._hotkey("selection")

    assert pdf_window.translate_calls == 0
    assert selection.request_calls == 1


def test_window_hotkey_returns_to_mode_chooser():
    calls: list[str] = []
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.mode_router = SimpleNamespace(
        pdf_window=None,
        show_chooser=lambda: calls.append("chooser"),
    )

    application._hotkey("window")

    assert calls == ["chooser"]


def test_closing_mode_chooser_only_hides_it(qtbot):
    router = ApplicationModeRouter(FakeWindow, FakeWindow)
    qtbot.addWidget(router.chooser)
    router.show_chooser()

    router.chooser.close()

    assert not router.chooser.isVisible()
    assert router.compact_window is None
    assert router.pdf_window is None
