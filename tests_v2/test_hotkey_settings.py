import pytest
from PySide6.QtCore import Qt

from learning_assistant.ui.settings_dialog import HotkeyEdit, SettingsDialog


def test_hotkey_editor_records_one_chord(qtbot):
    editor = HotkeyEdit()
    qtbot.addWidget(editor)
    editor.show()
    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key_R, Qt.ControlModifier | Qt.ShiftModifier)
    assert editor.text() == "Ctrl+Shift+R"


def test_hotkey_pair_validation():
    result = SettingsDialog._validated_hotkeys("Ctrl+Q", "Alt+F2")
    assert result == {
        "window_hotkey": "Ctrl+Q",
        "selection_hotkey": "Alt+F2",
        "pdf_highlight_hotkey": "Ctrl+H",
        "pdf_remove_highlight_hotkey": "Ctrl+R",
    }
    with pytest.raises(ValueError, match="相同"):
        SettingsDialog._validated_hotkeys("Alt+Q", "alt-q")
    with pytest.raises(ValueError, match="不能为空"):
        SettingsDialog._validated_hotkeys("", "Alt+W")
    with pytest.raises(ValueError, match="必须搭配"):
        SettingsDialog._validated_hotkeys("Q", "Alt+W")


@pytest.mark.parametrize("highlight,remove", [
    ("Ctrl+H", "control-h"), ("Alt+Q", "Ctrl+R"), ("Ctrl+H", "Alt+W"),
])
def test_pdf_hotkeys_reject_collisions_with_each_other_and_global_actions(highlight, remove):
    with pytest.raises(ValueError, match="相同"):
        SettingsDialog._validated_hotkeys("Alt+Q", "Alt+W", highlight, remove)


def test_pdf_hotkeys_save_reload_and_restore_defaults(qtbot, tmp_path):
    from learning_assistant.core.settings import SecretStore, SettingsStore
    from tests_v2.test_settings_models import ReadOnlyAutostart

    settings = SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"), tmp_path / "missing.json")
    dialog = SettingsDialog(settings, autostart=ReadOnlyAutostart())
    qtbot.addWidget(dialog)
    assert dialog.pdf_highlight_hotkey.text() == "Ctrl+H"
    assert dialog.pdf_remove_highlight_hotkey.text() == "Ctrl+R"
    qtbot.keyClick(dialog.pdf_highlight_hotkey, Qt.Key_K, Qt.ControlModifier)
    qtbot.keyClick(dialog.pdf_remove_highlight_hotkey, Qt.Key_M, Qt.ControlModifier)
    dialog._save_hotkeys()
    reopened = SettingsStore(settings.path, settings.secrets, settings.legacy_path)
    assert reopened.get("pdf_highlight_hotkey") == "Ctrl+K"
    assert reopened.get("pdf_remove_highlight_hotkey") == "Ctrl+M"
    next_dialog = SettingsDialog(reopened, autostart=ReadOnlyAutostart())
    qtbot.addWidget(next_dialog)
    assert next_dialog.pdf_highlight_hotkey.text() == "Ctrl+K"
    assert next_dialog.pdf_remove_highlight_hotkey.text() == "Ctrl+M"
    next_dialog._reset_hotkeys()
    next_dialog._save_hotkeys()
    reopened.load()
    assert reopened.get("pdf_highlight_hotkey") == "Ctrl+H"
    assert reopened.get("pdf_remove_highlight_hotkey") == "Ctrl+R"
