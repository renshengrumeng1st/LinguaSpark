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
    }
    with pytest.raises(ValueError, match="相同"):
        SettingsDialog._validated_hotkeys("Alt+Q", "alt-q")
    with pytest.raises(ValueError, match="不能为空"):
        SettingsDialog._validated_hotkeys("", "Alt+W")
    with pytest.raises(ValueError, match="必须搭配"):
        SettingsDialog._validated_hotkeys("Q", "Alt+W")
