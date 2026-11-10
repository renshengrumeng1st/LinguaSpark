import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import ModelProfile
from learning_assistant.ui.settings_dialog import SettingsDialog
from learning_assistant.ui.theme import apply_app_theme
from tests_v2.test_model_connection import model_server  # noqa: F401 - shared HTTP fixture


class ReadOnlyAutostart:
    def is_enabled(self):
        return False

    def set_enabled(self, enabled):
        raise AssertionError("Model tests must not change Windows autostart")


@pytest.fixture
def settings(tmp_path):
    return SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "credentials.json"), tmp_path / "absent.json")


def dialog_for(qtbot, settings):
    dialog = SettingsDialog(settings, autostart=ReadOnlyAutostart())
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def fill(dialog, url="https://example.com/v1", model="new-model"):
    dialog.name_edit.setText("新模型")
    dialog.url_edit.setText(url)
    dialog.key_edit.setText("test-only-key")
    dialog.model_edit.setText(model)


def test_add_starts_a_blank_draft_and_preserves_existing_model(qtbot, settings):
    settings.upsert_model(ModelProfile("original", "原模型", "https://original.test/v1", "original-model", "original-key"))
    dialog = dialog_for(qtbot, settings)
    qtbot.mouseClick(dialog.model_page.add_model_button, Qt.LeftButton)
    assert dialog.model_page.model_list.currentItem() is None
    assert [edit.text() for edit in (dialog.model_page.name_edit, dialog.model_page.url_edit, dialog.model_page.key_edit, dialog.model_page.model_edit)] == ["", "", "", ""]
    fill(dialog.model_page)
    qtbot.mouseClick(dialog.model_page.save_model_button, Qt.LeftButton)
    assert len(settings.models()) == 2
    assert settings.active_model().id == "original"
    assert settings.models()[0].api_key == "original-key"
    assert "test-only-key" not in settings.path.read_text(encoding="utf-8")


def test_editing_model_endpoint_updates_existing_entry(qtbot, settings):
    settings.upsert_model(ModelProfile("original", "原模型", "https://original.test/v1", "original-model", "original-key"))
    dialog = dialog_for(qtbot, settings)
    fill(dialog.model_page)
    qtbot.mouseClick(dialog.model_page.save_model_button, Qt.LeftButton)
    assert len(settings.models()) == 1
    assert settings.active_model().id == "original"
    assert settings.active_model().model == "new-model"


def test_adding_duplicate_endpoint_does_not_replace_credentials(qtbot, settings):
    settings.upsert_model(ModelProfile("original", "原模型", "https://example.com/v1", "new-model", "original-key"))
    dialog = dialog_for(qtbot, settings)
    qtbot.mouseClick(dialog.model_page.add_model_button, Qt.LeftButton)
    fill(dialog.model_page)
    qtbot.mouseClick(dialog.model_page.save_model_button, Qt.LeftButton)
    assert len(settings.models()) == 1
    assert settings.active_model().api_key == "original-key"
    assert dialog.model_page.form_status.property("state") == "error"


def test_connectivity_uses_unsaved_form_without_saving_credentials(qtbot, settings, model_server):
    dialog = dialog_for(qtbot, settings)
    fill(dialog.model_page, model_server.url)
    before = settings.path.read_bytes()
    qtbot.mouseClick(dialog.model_page.test_connection_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: dialog.model_page.connection_status.property("state") == "success", timeout=2500)
    assert model_server.requests[0][2]["model"] == "new-model"
    assert settings.path.read_bytes() == before
    assert settings.models() == []
    assert not settings.secrets.path.exists()


def test_editing_into_existing_endpoint_preserves_both_models(qtbot, settings):
    settings.upsert_model(ModelProfile("original", "原模型", "https://original.test/v1", "original-model", "original-key"))
    settings.upsert_model(ModelProfile("other", "另一模型", "https://example.com/v1/", "new-model", "other-key"), make_active=False)
    dialog = dialog_for(qtbot, settings)
    fill(dialog.model_page)
    qtbot.mouseClick(dialog.model_page.save_model_button, Qt.LeftButton)
    assert len(settings.models()) == 2
    assert settings.active_model().base_url == "https://original.test/v1"
    assert settings.models()[1].api_key == "other-key"
    assert dialog.model_page.form_status.property("state") == "error"


def test_closing_dialog_cancels_pending_connection(qtbot, settings, model_server):
    model_server.delay = 0.2
    dialog = dialog_for(qtbot, settings)
    fill(dialog.model_page, model_server.url)
    qtbot.mouseClick(dialog.model_page.test_connection_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(model_server.requests), timeout=2000)
    dialog.reject()
    qtbot.wait(300)
    assert dialog.model_page.connection_tester._reply is None
    assert dialog.model_page.connection_status.property("state") != "success"


def test_editing_form_invalidates_pending_connection_result(qtbot, settings, model_server):
    model_server.delay = 0.2
    dialog = dialog_for(qtbot, settings)
    fill(dialog.model_page, model_server.url)
    qtbot.mouseClick(dialog.model_page.test_connection_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(model_server.requests), timeout=2000)
    dialog.model_page.model_edit.setText("different-model")
    qtbot.wait(300)
    assert dialog.model_page.connection_status.property("state") != "success"
    assert dialog.model_page.test_connection_button.isEnabled()


def test_preset_fills_base_url_and_clears_previous_provider_credentials(qtbot, settings):
    page = dialog_for(qtbot, settings).model_page
    fill(page)
    page.provider_combo.setCurrentIndex(page.provider_combo.findText("LongCat"))
    assert page.url_edit.text() == "https://api.longcat.chat/openai/v1"
    assert page.key_edit.text() == ""
    assert page.model_edit.text() == ""
    assert settings.models() == []


def test_catalog_auto_fetch_preserves_typed_model_and_never_saves(qtbot, settings, model_server):
    model_server.payload = {"data": [{"id": "model-one"}, {"id": "model-two"}]}
    dialog = dialog_for(qtbot, settings)
    page = dialog.model_page
    before = settings.path.read_bytes()
    fill(page, model_server.url, "manual-model")
    qtbot.waitUntil(lambda: page.catalog_status.property("state") == "success", timeout=3500)
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == ["model-one", "model-two"]
    assert page.model_edit.text() == "manual-model"
    assert settings.path.read_bytes() == before
    assert not settings.secrets.path.exists()
    page.model_combo.setCurrentIndex(1)
    assert page._form_profile().model == "model-two"


def test_visible_dropdown_button_opens_available_models_for_selection(qtbot, settings, model_server):
    model_server.payload = {"data": [{"id": "model-one"}, {"id": "model-two"}]}
    dialog = dialog_for(qtbot, settings)
    dialog.activateWindow()
    qtbot.waitUntil(dialog.isActiveWindow)
    page = dialog.model_page
    fill(page, model_server.url)
    page.fetch_models_button.click()
    qtbot.waitUntil(lambda: page.catalog_status.property("state") == "success", timeout=2500)
    qtbot.mouseClick(page.model_dropdown_button, Qt.LeftButton)
    view = page.model_combo.view()
    qtbot.waitUntil(view.isVisible)
    index = page.model_combo.model().index(1, 0)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(index).center())
    assert page.model_edit.text() == "model-two"
    assert page._form_profile().model == "model-two"


def test_closing_dialog_cancels_catalog_and_pending_auto_fetch(qtbot, settings, model_server):
    model_server.delay = 0.2
    model_server.payload = {"data": [{"id": "late-model"}]}
    dialog = dialog_for(qtbot, settings)
    page = dialog.model_page
    fill(page, model_server.url)
    page.fetch_models_button.click()
    qtbot.waitUntil(lambda: bool(model_server.requests), timeout=2000)
    dialog.reject()
    qtbot.wait(1000)
    assert page.catalog_fetcher._reply is None
    assert page.catalog_status.property("state") != "success"
    assert len(model_server.requests) == 1


def test_output_budget_survives_save_and_is_used_in_requests(qtbot, settings):
    from learning_assistant.services.ai_client import QtAIClient
    from learning_assistant.domain.models import QueryKind, QueryRequest
    from tests_v2.test_ai_client import CaptureNetwork
    page = dialog_for(qtbot, settings).model_page
    fill(page)
    page.output_tokens_spin.setValue(8192)
    page.save_model_button.click()
    profile = settings.active_model()
    assert profile.max_output_tokens == 8192
    client = QtAIClient()
    client.network = CaptureNetwork()
    client.start(profile, QueryRequest("hello", QueryKind.WORD))
    assert client.network.payload["max_tokens"] == 8192


def test_theme_change_updates_existing_widgets_and_survives_reopen(qtbot, settings):
    app = QApplication.instance()
    previous = app.property("linguasparkTheme") or "sakura"
    dialog = dialog_for(qtbot, settings)
    try:
        dialog.navigation.setCurrentRow(2)
        qtbot.mouseClick(dialog.appearance_page.theme_buttons["dark"], Qt.LeftButton)
        assert app.palette().color(QPalette.Window).name() == "#151922"
        assert json.loads(settings.path.read_text(encoding="utf-8"))["appearance"]["theme"] == "dark"
        reopened = dialog_for(qtbot, settings)
        assert reopened.appearance_page.theme_buttons["dark"].isChecked()
        assert reopened.palette().color(QPalette.WindowText).name() == "#e8eaf2"
    finally:
        apply_app_theme(previous)
