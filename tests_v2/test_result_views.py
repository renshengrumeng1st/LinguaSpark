from PySide6.QtCore import Qt

from learning_assistant.domain.models import AiStudyNote
from learning_assistant.ui.result_views import WordResultView


def test_example_speech_uses_only_source_sentences(qtbot):
    view = WordResultView()
    qtbot.addWidget(view)
    view.show_note(AiStudyNote(examples=[
        {"sentence": "Keep it simple", "translation": "保持简单"},
        {"sentence": "Speak naturally", "translation": "自然地说"},
    ]))
    with qtbot.waitSignal(view.speak_requested) as signal:
        qtbot.mouseClick(view.example_speak_button, Qt.LeftButton)
    assert signal.args == ["Keep it simple. Speak naturally"]
