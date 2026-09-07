from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from learning_assistant.application import (
    ApplicationModeRouter,
    LearningAssistantApplication,
)
from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.storage.learning_repository import LearningRepository


def test_importing_application_does_not_eagerly_load_qt_webengine() -> None:
    """Compact-mode cold start must not pay Chromium's import cost."""
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import learning_assistant.application; "
            "print('PySide6.QtWebEngineWidgets' in sys.modules)",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "False"


def test_application_installs_project_icon_for_top_level_windows(qtbot) -> None:
    """Dropping the application-level icon must restore the blank Qt icon."""
    qt = QApplication.instance()
    assert qt is not None
    previous_icon = qt.windowIcon()
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.qt = qt

    try:
        icon = application._install_application_icon()
        router = ApplicationModeRouter(FakeWindow, FakeWindow)
        qtbot.addWidget(router.chooser)

        assert not icon.isNull()
        assert qt.windowIcon().cacheKey() == icon.cacheKey()
        assert router.chooser.windowIcon().cacheKey() == icon.cacheKey()
        assert {(size.width(), size.height()) for size in icon.availableSizes()} >= {
            (16, 16),
            (32, 32),
            (48, 48),
            (256, 256),
        }
    finally:
        qt.setWindowIcon(previous_icon)


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


def test_window_hotkey_toggles_compact_mode_visibility(qtbot):
    router = ApplicationModeRouter(FakeWindow, FakeWindow)
    qtbot.addWidget(router.chooser)
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.mode_router = router

    application._hotkey("window")
    compact = router.compact_window
    assert compact is not None
    qtbot.addWidget(compact)
    assert compact.isVisible()

    application._hotkey("window")
    assert not compact.isVisible()

    application._hotkey("window")
    assert compact.isVisible()
    assert compact.front_calls == 2


def test_pdf_controller_factory_shares_one_network_client(qtbot, tmp_path):
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.qt = QApplication.instance()
    application.settings = SettingsStore(
        tmp_path / "settings.json",
        secrets=SecretStore(tmp_path / "secrets.json"),
        legacy_path=tmp_path / "missing.json",
    )
    application.repository = LearningRepository(tmp_path / "learning.sqlite3")
    application.pdf_client = None

    first = application._create_pdf_controller()
    second = application._create_pdf_controller()

    assert first is not second
    assert first.client is second.client
    assert first.client is application.pdf_client
    first.dispose()
    second.dispose()


def test_closing_mode_chooser_only_hides_it(qtbot):
    router = ApplicationModeRouter(FakeWindow, FakeWindow)
    qtbot.addWidget(router.chooser)
    router.show_chooser()

    router.chooser.close()

    assert not router.chooser.isVisible()
    assert router.compact_window is None
    assert router.pdf_window is None


def test_startup_argument_is_recognized() -> None:
    assert LearningAssistantApplication._startup_requested(
        ["LinguaSpark.exe", "--startup"]
    )
    assert not LearningAssistantApplication._startup_requested(["LinguaSpark.exe"])


def test_startup_launch_stays_quiet_in_the_system_tray(qtbot) -> None:
    router = ApplicationModeRouter(FakeWindow, FakeWindow)
    qtbot.addWidget(router.chooser)
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.hotkeys = SimpleNamespace(start=lambda: None)
    application.review_timer = SimpleNamespace(start=lambda: None)
    application.dictionary = SimpleNamespace(available=True)
    application.mode_router = router
    application.qt = SimpleNamespace(exec=lambda: 0)
    application._startup_launch = True

    assert application.run() == 0
    assert not router.chooser.isVisible()
    assert router.compact_window is None
    assert router.pdf_window is None
