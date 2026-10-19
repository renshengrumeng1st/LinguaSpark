import json
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import DictionaryEntry, QueryKind, QueryRequest, SentenceResult
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.main_window import MainWindow
from learning_assistant.ui.selection_popup import SelectionPopup


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


def test_sentence_translation_appears_before_completion_in_compact_surfaces(qtbot, tmp_path: Path):
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
    popup = SelectionPopup(controller)
    qtbot.addWidget(window)
    qtbot.addWidget(popup)
    window.show()
    popup.show_query("Good morning.", QPoint(100, 100))
    controller.query_started.emit(QueryRequest("Good morning.", QueryKind.SENTENCE))

    controller.ai_partial.emit("早上好")

    assert window.scroll.isVisible()
    assert window.sentence_view.translation.text() == "早上好"
    assert popup.content.text() == "早上好"

    controller.sentence_ready.emit(SentenceResult(
        translation="早上好。", learning_tip="用于问候。",
    ), False)
    assert window.sentence_view.translation.text() == "早上好。"
    assert popup.content.text() == "早上好。"


def test_sentence_favorite_waits_for_complete_payload(qtbot, tmp_path: Path):
    settings = SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "no-legacy.json",
    )
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    controller = LearningController(
        settings,
        DictionaryRepository(tmp_path / "missing.sqlite3"),
        repository,
    )
    window = MainWindow(controller, settings, FakeSpeech())
    qtbot.addWidget(window)
    window.show()
    controller._active = QueryRequest("Good morning.", QueryKind.SENTENCE)
    controller._active_request_id = 7
    controller._active_cache_key = "test-sentence"
    window.sentence_view.set_favorite(True)
    controller.query_started.emit(controller._active)
    controller.ai.partial.emit(7, '{"translation":"早上好')

    assert window.scroll.isVisible()
    assert not window.sentence_view.favorite_button.isEnabled()
    assert window.sentence_view.favorite_button.text() == "收藏"
    qtbot.mouseClick(window.sentence_view.favorite_button, Qt.LeftButton)
    assert not controller.is_current_favorite()

    controller.ai.completed.emit(7, {
        "translation": "早上好。", "key_phrases": [], "learning_tip": "用于问候。",
    }, {})
    assert window.sentence_view.favorite_button.isEnabled()
    qtbot.mouseClick(window.sentence_view.favorite_button, Qt.LeftButton)
    saved = repository._connection().execute(
        "SELECT payload FROM favorites"
    ).fetchone()[0]
    assert json.loads(saved)["sentence"]["translation"] == "早上好。"
    repository._connection().close()
