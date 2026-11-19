from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QHelpEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from learning_assistant.ui.pdf_themes import READING_THEMES
from tests_v2.test_pdf_learning_ui import setup_tab


def test_reference_tooltip_wraps_and_uses_current_reading_paper_color(qtbot, tmp_path):
    tab, _, _, _, _ = setup_tab(qtbot, tmp_path)
    tab.resize(1100, 800)
    with qtbot.waitActive(tab):
        tab.show()
        tab.activateWindow()
    tab.set_theme("paper")
    panel = tab.qa_panel
    panel.controller.page_count = 1
    quote = ('the fixed points encode how much each criterion should count, '
             'not how strongly its verdict distinguishes the current rollouts ')*2
    panel.controller.started.emit("Explain", "")
    panel.controller.completed.emit(f"Evidence [第 1 页｜{quote.strip()}]")
    tab.toggle_question()
    panel.question_input.setFocus()
    qtbot.waitUntil(panel.question_input.hasFocus)
    browser = panel.answer_browser
    cursor = browser.document().find("[第 1 页]")
    assert not cursor.isNull()
    pos = browser.cursorRect(cursor).center()
    pos.setX(pos.x() - 3)
    event = QHelpEvent(QEvent.ToolTip, pos, browser.viewport().mapToGlobal(pos))
    QApplication.sendEvent(browser.viewport(), event)
    tip = browser.findChild(QFrame, "pdfCitationTooltip")
    assert tip is not None and tip.isVisible()
    assert tip.width() <= 420
    label = tip.findChild(QLabel)
    assert label.wordWrap() and label.textFormat() == Qt.PlainText
    assert label.text() == quote.strip()
    assert panel.question_input.hasFocus()
    for theme in ("paper", "soft_gray", "eye_care", "white"):
        tab.set_theme(theme)
        qtbot.waitUntil(lambda: tip.palette().color(tip.backgroundRole()) == QColor(READING_THEMES[theme]))
        pixel = tip.grab().toImage().pixelColor(7, 7)
        expected = QColor(READING_THEMES[theme])
        assert max(abs(pixel.red()-expected.red()), abs(pixel.green()-expected.green()),
                   abs(pixel.blue()-expected.blue())) < 4
    QApplication.sendEvent(browser.viewport(), QEvent(QEvent.Leave))
    assert not tip.isVisible()
    tab.close_session()
