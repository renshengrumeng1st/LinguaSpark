from pathlib import Path

from PySide6.QtCore import QObject, Signal

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import DictionaryEntry
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.main_window import MainWindow


class FakeSpeech(QObject):
    failed = Signal(str)

    def speak(self, text: str, locale: str = "en-US") -> bool:
        return bool(text)


def test_main_window_constructs_and_validates_input(qtbot, tmp_path: Path):
    settings = SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "no-legacy.json",
    )
    controller = LearningController(
        settings=settings,
        dictionary=DictionaryRepository(tmp_path / "missing.sqlite3"),
        repository=LearningRepository(tmp_path / "learning.sqlite3"),
    )
    window = MainWindow(controller, settings, FakeSpeech())
    qtbot.addWidget(window)
    window.show()
    assert not window.scroll.isVisible()
    window.input.setPlainText("hello world")
    window.submit()
    assert "设置" in window.status.text()


def test_window_expands_when_local_word_result_arrives(qtbot, tmp_path: Path):
    settings = SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "no-legacy.json",
    )
    controller = LearningController(
        settings=settings,
        dictionary=DictionaryRepository(tmp_path / "missing.sqlite3"),
        repository=LearningRepository(tmp_path / "learning.sqlite3"),
    )
    window = MainWindow(controller, settings, FakeSpeech())
    qtbot.addWidget(window)
    window.show()
    initial_height = window.height()
    window._on_word(DictionaryEntry(
        word="test", lemma="test", translations=["n. 测试", "v. 检验"]
    ), 1)
    qtbot.wait(220)
    assert window.scroll.isVisible()
    assert window.height() > initial_height
    assert window.word_view.meanings.text() == "• n. 测试\n• v. 检验"
