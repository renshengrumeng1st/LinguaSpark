import pytest
from PySide6.QtCore import QObject, Signal, Qt

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import DictionaryEntry, ModelProfile
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.main_window import MainWindow
from tests_v2.test_ui_smoke import FakeSpeech


class Dictionary:
    @staticmethod
    def is_word(text):
        return text.isascii() and text.isalpha()

    def lookup(self, text, language="en"):
        return DictionaryEntry(text, translations=["测试释义"])


class AI(QObject):
    partial = Signal(int, str)
    completed = Signal(int, object, object)
    failed = Signal(int, str, object)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.cancelled = []

    def start(self, profile, request, entry=None):
        self.calls.append(request)
        return len(self.calls)

    def cancel(self, request_id):
        self.cancelled.append(request_id)


@pytest.fixture
def experience(qtbot, tmp_path):
    settings = SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"), tmp_path / "absent.json")
    settings.upsert_model(ModelProfile("test", "Test", "https://example.test/v1", "test", "test-only"))
    settings.set("auto_lookup_delay_ms", 80)
    settings.set("auto_ai_delay_ms", 400)
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    ai = AI()
    controller = LearningController(settings, Dictionary(), repo, ai)
    speech = FakeSpeech()
    window = MainWindow(controller, settings, speech)
    qtbot.addWidget(window)
    window.show()
    yield window, controller, ai, repo, settings
    window.auto_timer.stop()
    if hasattr(window, "ai_timer"):
        window.ai_timer.stop()
    controller.cancel()
    repo._connection().close()


def test_local_result_precedes_single_debounced_ai_request(qtbot, experience):
    window, controller, ai, repo, _ = experience
    window.input.setPlainText("chi")
    qtbot.waitUntil(lambda: window.word_view.word.text() == "chi")
    assert not ai.calls
    window.input.setPlainText("chin")
    qtbot.waitUntil(lambda: len(ai.calls) == 1)
    assert ai.calls[0].text == "chin"
    qtbot.wait(450)
    assert len(ai.calls) == 1


def test_manual_submit_does_not_leave_an_automatic_duplicate(qtbot, experience):
    window, _, ai, _, _ = experience
    window.input.setPlainText("chin")
    window.submit()
    qtbot.wait(500)
    assert len(ai.calls) == 1


def test_turning_off_auto_ai_keeps_local_lookup_and_manual_submit(qtbot, experience):
    window, _, ai, _, _ = experience
    qtbot.mouseClick(window.auto_ai_checkbox, Qt.LeftButton)
    window.input.setPlainText("chin")
    qtbot.waitUntil(lambda: window.word_view.word.text() == "chin")
    qtbot.wait(500)
    assert not ai.calls
    window.submit()
    assert len(ai.calls) == 1


def test_edit_and_clear_ignore_late_results(qtbot, experience):
    window, _, ai, _, _ = experience
    window.input.setPlainText("chin")
    window.submit()
    window.input.setPlainText("china")
    ai.completed.emit(1, {"plain_explanation": "旧结果"}, {})
    assert window.word_view.plain.value.text() != "旧结果"
    window.clear()
    qtbot.wait(500)
    assert len(ai.calls) == 1


def test_retry_bypasses_cache_and_keeps_the_local_definition(qtbot, experience):
    window, controller, ai, repo, _ = experience
    window.input.setPlainText("chin")
    window.submit()
    ai.failed.emit(1, "暂时不可用", {})
    repo.put_ai_cache(controller._active_cache_key, {"plain_explanation": "旧缓存"})
    assert window.retry_button.isVisible()
    qtbot.mouseClick(window.retry_button, Qt.LeftButton)
    assert len(ai.calls) == 2
    assert "测试释义" in window.word_view.meanings.text()


def test_saved_result_opens_without_network(qtbot, experience):
    window, controller, ai, repo, _ = experience
    repo.add_history("chin", "word", {"dictionary": {"word": "chin", "translations": ["下巴"]}, "ai_note": {"plain_explanation": "保存的解释"}}, "en", "zh-CN")
    window.open_saved(repo.saved_items()[0])
    qtbot.wait(550)
    assert not ai.calls
    assert window.word_view.plain.value.text() == "保存的解释"
    assert controller._active.text == "chin"


def test_saved_search_pagination_and_deletion_are_isolated(tmp_path):
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    try:
        repo.add_history("chin", "word", {"meaning": "下巴"}, "en", "zh-CN")
        repo.add_history("Hello there.", "sentence", {"sentence": {"translation": "你好"}}, "en", "zh-CN")
        repo.toggle_favorite("chin", "word", {"meaning": "下巴"})
        rows = repo.saved_items(search="下巴", kind="word")
        assert len(rows) == 1
        assert len(repo.saved_items(limit=1)) == 1
        assert len(repo.saved_items(limit=1, offset=1)) == 1
        assert repo.saved_items(search="' OR 1=1 --") == []
        assert repo.delete_saved("history", rows[0]["identifier"])
        assert repo.is_favorite("chin", "word")
    finally:
        repo._connection().close()


@pytest.mark.parametrize("theme", ["nahida", "furina", "raiden"])
def test_character_theme_survives_reload(tmp_path, theme):
    store = SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"), tmp_path / "absent.json")
    store.set("appearance", {"theme": theme})
    store.save()
    store.load()
    assert store.get("appearance")["theme"] == theme


def test_library_search_and_reopen_are_offline(qtbot, experience):
    window, _, ai, repo, _ = experience
    repo.add_history("chin", "word", {"dictionary": {"word": "chin", "translations": ["下巴"]}}, "en", "zh-CN")
    repo.add_history("Hello there.", "sentence", {"sentence": {"translation": "你好"}}, "en", "zh-CN")
    window.open_library()
    library = window._library_dialog
    library.search.setText("下巴")
    qtbot.waitUntil(lambda: library.item_list.count() == 1)
    assert "下巴" in library.detail.toPlainText()
    qtbot.mouseClick(library.open_button, Qt.LeftButton)
    qtbot.wait(500)
    assert "下巴" in window.word_view.meanings.text()
    assert not ai.calls


def test_local_preview_keeps_previous_complete_history(tmp_path):
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    try:
        repo.add_history("chin", "word", {"dictionary": {"word": "chin"}, "ai_note": {"plain_explanation": "完整解释"}}, "en", "zh-CN")
        repo.add_history("chin", "word", {"dictionary": {"word": "chin", "translations": ["下巴"]}}, "en", "zh-CN")
        rows = repo.saved_items()
        assert len(rows) == 1
        assert rows[0]["payload"]["ai_note"]["plain_explanation"] == "完整解释"
    finally:
        repo._connection().close()


def test_character_previews_render_and_select(qtbot, experience):
    from learning_assistant.ui.appearance_settings import AppearanceSettingsPage
    from learning_assistant.ui.theme import apply_app_theme

    _, _, _, _, settings = experience
    page = AppearanceSettingsPage(settings)
    qtbot.addWidget(page)
    page.resize(750, 1100)
    page.show()
    try:
        assert not page.grab().isNull()
        qtbot.mouseClick(page.theme_buttons["furina"], Qt.LeftButton)
        assert settings.get("appearance")["theme"] == "furina"
        assert not page.grab().isNull()
    finally:
        apply_app_theme("sakura")


def test_retyping_cancelled_word_can_start_a_new_request(qtbot, experience):
    window, _, ai, _, _ = experience
    window.input.setPlainText("chin")
    window.submit()
    window.input.setPlainText("china")
    window.input.setPlainText("chin")
    qtbot.waitUntil(lambda: len(ai.calls) == 2)
    assert ai.cancelled == [1]


def test_switching_model_cancels_pending_auto_request(qtbot, experience):
    window, _, ai, _, settings = experience
    settings.upsert_model(ModelProfile("other", "Other", "https://other.test/v1", "test", "test-only"), make_active=False)
    window._reload_models()
    window.input.setPlainText("chin")
    window.model_combo.setCurrentIndex(1)
    qtbot.wait(550)
    assert not ai.calls


def test_unknown_word_error_is_visible_and_retryable(experience):
    window, controller, ai, _, _ = experience
    controller.dictionary.lookup = lambda *args: None
    window.input.setPlainText("unlistedword")
    window.submit()
    ai.failed.emit(1, "服务暂时不可用", {})
    assert window.scroll.isVisible()
    assert window.retry_button.isVisible()
    assert "服务暂时不可用" in window.word_view.ai_state.text()
