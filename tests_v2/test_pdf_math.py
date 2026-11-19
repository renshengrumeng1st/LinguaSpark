from PySide6.QtWidgets import QTextBrowser
from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
from learning_assistant.ui.pdf_translation_panel import PdfTranslationPanel
from tests_v2.test_pdf_questions import make_controller


def test_answer_and_translation_render_math_offline_preserving_raw_copy(qtbot, tmp_path):
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.resize(420, 600)
    panel.show()
    answer = r'加权平均为 \[R_{\mathrm{base}}=\frac{\sum_j w_j G_{ij}}{\sum_j w_j}\]，其中 \(G_{ij}\in\{0,1\}\)。[第 1 页｜First page]'
    panel.question_input.setPlainText("Explain reward")
    panel.send_button.click()
    loader.loaded.emit(("First page",))
    client.completed.emit(1, answer)
    translation = PdfTranslationPanel()
    qtbot.addWidget(translation)
    translation.finish_translation(r'译文公式：\(w_j > 0\)。')
    qtbot.waitUntil(lambda: panel.answer_browser.toHtml().count('<img ') == 2
                   and translation.answer_browser.toHtml().count('<img ') == 1, timeout=15000)
    assert not panel.answer_browser.document().find("[第 1 页]").isNull()
    panel.copy_button.click()
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == answer
    assert panel.findChildren(QTextBrowser) == [panel.answer_browser]
    panel.dispose()
    translation.dispose()


def test_streamed_formula_waits_for_closing_delimiter_and_fits_narrow_sidebar(qtbot, tmp_path):
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    panel.resize(500, 500)
    panel.show()
    panel.question_input.setPlainText("Explain")
    panel.send_button.click()
    loader.loaded.emit(("First page",))
    client.partial.emit(1, r'Formula \[\sum_{j=1}^{100} w_j G_{ij}')
    qtbot.waitUntil(lambda: "sum" in panel.answer_browser.toPlainText())
    assert '<img ' not in panel.answer_browser.toHtml()
    client.partial.emit(1, r'\]')
    qtbot.waitUntil(lambda: '<img ' in panel.answer_browser.toHtml(), timeout=15000)
    panel.resize(230, 500)
    qtbot.waitUntil(lambda: panel.answer_browser.document().idealWidth() <= panel.answer_browser.viewport().width() + 2)
    assert "Formula" in panel.answer_browser.toPlainText()
    panel.dispose()


def test_invalid_math_and_model_html_remain_safe_readable_text(qtbot, tmp_path):
    panel = PdfTranslationPanel()
    qtbot.addWidget(panel)
    panel.finish_translation(r'Broken \(\unknownCommand{x}\) <img src="https://example.test/tracker">')
    qtbot.waitUntil(lambda: not panel.math_renderer.pending, timeout=15000)
    text = panel.answer_browser.toPlainText()
    assert r'\unknownCommand{x}' in text
    assert '<img src="https://example.test/tracker">' in text
    assert '<img ' not in panel.answer_browser.toHtml()
    panel.dispose()
