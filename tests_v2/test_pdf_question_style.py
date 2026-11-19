from PySide6.QtCore import Qt

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import LanguageProfile, ModelProfile
from learning_assistant.services.pdf_questions import QtPdfQuestionClient
from learning_assistant.ui.settings_dialog import SettingsDialog
from tests_v2.test_model_connection import model_server  # noqa: F401
from tests_v2.test_pdf_questions import make_controller
from tests_v2.test_settings import SandboxedSecretStore
from tests_v2.test_settings_models import ReadOnlyAutostart


def test_style_save_reopen_and_restore_default(qtbot, tmp_path):
    settings = SettingsStore(tmp_path / "settings.json", SandboxedSecretStore(tmp_path / "keys.json"),
                             tmp_path / "missing.json")
    assert settings.get("pdf_question_answer_style") == ""
    dialog = SettingsDialog(settings, autostart=ReadOnlyAutostart())
    qtbot.addWidget(dialog)
    dialog.navigation.setCurrentRow(dialog.navigation.count() - 1)
    dialog.show()
    assert dialog.page_title.text() == "PDF 问答"
    assert dialog.pdf_answer_style.toPlainText() == ""
    style = "先用一句话给出结论。\n再用适合初学者的语言解释。"
    dialog.pdf_answer_style.setPlainText(style)
    qtbot.mouseClick(dialog.save_pdf_question_button, Qt.LeftButton)
    reopened = SettingsStore(settings.path, settings.secrets, settings.legacy_path)
    assert reopened.get("pdf_question_answer_style") == style
    next_dialog = SettingsDialog(reopened, autostart=ReadOnlyAutostart())
    qtbot.addWidget(next_dialog)
    assert next_dialog.pdf_answer_style.toPlainText() == style
    qtbot.mouseClick(next_dialog.reset_pdf_question_button, Qt.LeftButton)
    assert next_dialog.pdf_answer_style.toPlainText() == ""
    # Reset is a draft change until the user saves it.
    assert reopened.get("pdf_question_answer_style") == style
    qtbot.mouseClick(next_dialog.save_pdf_question_button, Qt.LeftButton)
    reopened.load()
    assert reopened.get("pdf_question_answer_style") == ""


def test_style_preserves_rules_document_and_stable_prefix():
    profile = ModelProfile("m", "Test", "https://example.test/v1", "model", "key")
    args = (profile, ("First page", "Final page"), "Question", [], LanguageProfile())
    default = QtPdfQuestionClient.build_payload(*args)
    blank = QtPdfQuestionClient.build_payload(*args, answer_style="  \n ")
    assert default == blank
    style = "先给结论，再分步骤解释。"
    first = QtPdfQuestionClient.build_payload(*args, answer_style=style)
    assert first["messages"][0]["content"].startswith(default["messages"][0]["content"])
    assert style in first["messages"][0]["content"]
    assert first["messages"][1:] == default["messages"][1:]
    history = [first["messages"][-1], {"role": "assistant", "content": "Answer"}]
    followup = QtPdfQuestionClient.build_payload(profile, args[1], "Follow up", history,
                                               LanguageProfile(), answer_style=style)
    assert first["messages"][:2] == followup["messages"][:2]


def test_each_question_snapshots_latest_style_even_while_loading(tmp_path):
    controller, client, loader, settings, _ = make_controller(tmp_path)
    settings.set("pdf_question_answer_style", "简洁回答")
    controller.ask("First question")
    settings.set("pdf_question_answer_style", "详细解释")
    loader.loaded.emit(("PDF text",))
    assert client.answer_styles == ["简洁回答"]
    client.completed.emit(1, "First answer")
    controller.ask("Follow up")
    assert client.answer_styles == ["简洁回答", "详细解释"]
    controller.dispose()


def test_custom_style_reaches_http_request(qtbot, qapp, model_server):
    model_server.payload = {"choices": [{"message": {"content": "Answer"}, "finish_reason": "stop"}]}
    client = QtPdfQuestionClient(qapp)
    with qtbot.waitSignal(client.completed, timeout=4000):
        client.start(ModelProfile("m", "Test", model_server.url, "model", "test-key"),
                     ("PDF text",), "Question", [], LanguageProfile(), answer_style="请简洁回答")
    assert "请简洁回答" in model_server.requests[0][2]["messages"][0]["content"]
