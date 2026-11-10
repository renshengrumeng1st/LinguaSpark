import pytest
from PySide6.QtCore import Qt

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import AiStudyNote, ModelProfile, QueryKind, QueryRequest
from learning_assistant.ui.main_window import MainWindow
from learning_assistant.ui.result_views import WordResultView
from tests_v2.test_convenience import AI, Dictionary
from tests_v2.test_ui_smoke import FakeSpeech
from learning_assistant.controller import LearningController
from learning_assistant.storage.learning_repository import LearningRepository


@pytest.fixture
def experience(qtbot, tmp_path):
    settings = SettingsStore(
        tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"),
        tmp_path / "absent.json",
    )
    settings.set("auto_lookup_delay_ms", 80)
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    ai = AI()
    controller = LearningController(settings, Dictionary(), repo, ai)
    window = MainWindow(controller, settings, FakeSpeech())
    qtbot.addWidget(window)
    window.show()
    yield window, controller, ai, repo, settings
    window.auto_timer.stop()
    window.ai_timer.stop()
    controller.cancel()
    repo._connection().close()


def _note():
    return AiStudyNote(
        plain_explanation="容易理解的解释", sense_in_context="语境中的意思",
        synonyms=["simple"], collocations=["keep it simple"],
        common_mistake="注意词形", memory_tip="联想记忆",
        examples=[{"sentence": "Keep it simple.", "translation": "保持简单。"}],
    )


def test_no_model_guidance_keeps_local_lookup_without_pending_ai(qtbot, experience):
    window, _, ai, _, _ = experience
    assert "本地查词可用" in window.availability_label.text()
    assert "待配置" in window.availability_label.text()
    assert window.configure_ai_button.isVisible()
    assert not window.auto_ai_checkbox.isEnabled()
    window.input.setPlainText("hello")
    qtbot.waitUntil(lambda: window.word_view.entry is not None)
    assert not window.ai_timer.isActive()
    assert "测试释义" in window.word_view.meanings.text()
    assert "配置" in window.word_view.ai_state.text()
    assert not ai.calls


def test_model_guidance_refreshes_after_configuration(experience):
    window, _, ai, _, settings = experience
    settings.upsert_model(ModelProfile("ready", "Ready", "https://example.test/v1", "test", "test-key"))
    window._reload_models()
    assert "AI 已就绪" in window.availability_label.text()
    assert not window.configure_ai_button.isVisible()
    assert window.auto_ai_checkbox.isEnabled()
    assert not ai.calls


@pytest.mark.parametrize("profile", [
    ModelProfile("disabled", "Disabled", "https://example.test/v1", "test", "test-key", enabled=False),
    ModelProfile("missing-name", "Missing model", "https://example.test/v1", "", "test-key"),
    ModelProfile("missing-url", "Missing URL", "", "test", "test-key"),
    ModelProfile("missing-key", "Missing key", "https://example.test/v1", "test"),
])
def test_incomplete_or_disabled_model_does_not_start_ai(experience, profile):
    window, _, ai, _, settings = experience
    settings.upsert_model(profile)
    window._reload_models()
    window.input.setPlainText("hello")
    window.submit()
    assert window.configure_ai_button.isVisible()
    assert not ai.calls
    assert "测试释义" in window.word_view.meanings.text()


def test_offline_example_never_schedules_ai_even_with_model(qtbot, experience):
    window, _, ai, repo, settings = experience
    settings.upsert_model(ModelProfile("ready", "Ready", "https://example.test/v1", "test", "test-key"))
    window._reload_models()
    qtbot.mouseClick(window.example_button, Qt.LeftButton)
    assert window.word_view.entry is not None
    assert not window.auto_timer.isActive()
    assert not window.ai_timer.isActive()
    assert not ai.calls
    assert repo.saved_items() == []


def test_word_result_uses_compact_input_and_clear_restores_it(experience):
    window, _, _, _, _ = experience
    initial_height = window.input_card.height()
    window.input.setPlainText("hello")
    window.submit()
    assert window.input_card.height() < initial_height
    assert window.brand_subtitle.isHidden()
    window.input.setPlainText("A full sentence.")
    window._on_started(QueryRequest("A full sentence.", QueryKind.SENTENCE))
    assert window.input_card.height() >= initial_height
    assert not window.brand_subtitle.isHidden()
    window.clear()
    assert window.input_card.height() == initial_height
    assert window.welcome.isVisible()


def test_details_fold_without_losing_copy_favorite_or_study(qtbot, experience):
    window, controller, _, repo, _ = experience
    window.input.setPlainText("hello")
    window.submit()
    note = _note()
    controller._current_payload["ai_note"] = note.to_dict()
    window._on_note(note, False)
    view = window.word_view
    assert view.plain.isVisible()
    assert view.context.isVisible()
    assert view.collocations.isVisible()
    assert view.examples.isVisible()
    assert not view.synonyms.isVisible()
    assert not view.mistake.isVisible()
    assert not view.memory.isVisible()
    with qtbot.waitSignal(view.copy_requested) as copied:
        qtbot.mouseClick(view.copy_button, Qt.LeftButton)
    assert "simple" in copied.args[0]
    assert "注意词形" in copied.args[0]
    assert "联想记忆" in copied.args[0]
    qtbot.mouseClick(view.favorite_button, Qt.LeftButton)
    qtbot.mouseClick(view.study_button, Qt.LeftButton)
    assert controller.is_current_favorite()
    assert controller.is_current_study()
    assert repo.saved_items("favorites")[0]["payload"]["ai_note"]["memory_tip"] == "联想记忆"
    qtbot.mouseClick(view.more_button, Qt.LeftButton)
    assert view.synonyms.isVisible()
    assert view.mistake.isVisible()
    assert view.memory.isVisible()


def test_details_preference_persists_without_stale_copy(qtbot, experience):
    window, controller, _, _, settings = experience
    window.input.setPlainText("hello")
    window.submit()
    window._on_note(_note(), False)
    qtbot.mouseClick(window.word_view.more_button, Qt.LeftButton)
    restored_settings = SettingsStore(settings.path, settings.secrets, settings.legacy_path)
    restored = MainWindow(controller, restored_settings, FakeSpeech())
    qtbot.addWidget(restored)
    restored.word_view.show_note(_note())
    assert restored.word_view.more_button.isChecked()
    assert not restored.word_view.more_content.isHidden()
    restored.word_view.show_query("newword")
    assert "联想记忆" not in restored.word_view.plain_text()
    assert restored.word_view.more_button.isHidden()


def test_copy_includes_details_when_view_itself_is_hidden(qtbot):
    view = WordResultView()
    qtbot.addWidget(view)
    view.show_note(_note())
    assert "容易理解的解释" in view.plain_text()
    assert "联想记忆" in view.plain_text()


@pytest.mark.parametrize("image", [False, True])
def test_unconfigured_ai_preserves_sentence_or_image_with_visible_setup_hint(experience, image):
    window, _, ai, _, _ = experience
    window.input.setPlainText("Keep it simple.")
    if image:
        window.image_bytes = b"preview"
    window.submit()
    assert not ai.calls
    assert window.input.toPlainText() == "Keep it simple."
    assert window.image_bytes == (b"preview" if image else None)
    assert "配置 AI 模型" in window.status.text()
    assert window.configure_ai_button.isVisible()


def test_setup_button_opens_real_model_settings_page(qtbot, experience):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from learning_assistant.ui.settings_dialog import SettingsDialog
    window, _, _, _, _ = experience
    pages = []
    def close_settings():
        dialogs = [widget for widget in QApplication.topLevelWidgets() if isinstance(widget, SettingsDialog)]
        for dialog in dialogs:
            pages.append(dialog.navigation.currentRow())
            dialog.reject()
    QTimer.singleShot(100, close_settings)
    window.configure_ai_button.click()
    assert pages == [1]
