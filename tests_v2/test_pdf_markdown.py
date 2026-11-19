import pytest
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from learning_assistant.ui.pdf_question_panel import PdfQuestionPanel
from learning_assistant.ui.pdf_translation_panel import PdfTranslationPanel
from tests_v2.test_pdf_questions import make_controller


@pytest.fixture(params=["question", "translation"])
def output(request, qtbot, tmp_path):
    if request.param == "translation":
        panel = PdfTranslationPanel()
        show_answer = panel.finish_translation
    else:
        controller, client, loader, settings, _ = make_controller(tmp_path)
        panel = PdfQuestionPanel(settings, controller=controller)
        panel.question_input.setPlainText("解释这项实验")
        panel.send_button.click()
        loader.loaded.emit(("First page",))
        show_answer = lambda text: client.completed.emit(1, text)
    qtbot.addWidget(panel)
    yield panel, show_answer
    panel.dispose()


def test_markdown_formats_chinese_bold_headings_lists_tables_and_code(output):
    panel, show_answer = output
    show_answer("**1. 它说的是什么实验**\n\n实验对象是**已经训练过的策略**产生的 rollout。\n\n"
                "## 实验结果\n\n- 第一项\n- 第二项\n\n"
                "| 指标 | 数值 |\n| --- | --- |\n| 相关性 | 95% |\n\n`GRPO_value`")
    document = panel.answer_browser.document()
    text = document.toPlainText()
    assert "**" not in text
    assert document.find("已经训练过的策略").charFormat().fontWeight() >= QFont.Weight.Bold
    assert document.find("实验结果").blockFormat().headingLevel() == 2
    assert document.find("第一项").block().textList() is not None
    assert document.find("相关性").currentTable() is not None
    assert QFontInfo(document.find("GRPO_value").charFormat().font()).fixedPitch()


def test_empty_output_preserves_generation_status(output):
    panel, _ = output
    if isinstance(panel, PdfTranslationPanel):
        panel.start_translation()
        expected = "翻译中…"
    else:
        expected = "回答中…"
    assert expected in panel.answer_browser.toPlainText()


def test_markdown_keeps_code_literal_and_disables_model_images_and_links(output):
    panel, show_answer = output
    show_answer('`\\(x_i\\)`\n\n```text\n[第 1 页｜First page]\n\\[y_j\\]\n```\n\n'
                '![外部图片](https://example.test/image.png)\n\n'
                '[伪造引用](pdf-citation:0)\n\n<img src="file:///private">')
    document = panel.answer_browser.document()
    text = document.toPlainText()
    assert r"\(x_i\)" in text and r"\[y_j\]" in text
    assert "[第 1 页｜First page]" in text
    assert "外部图片" in text
    assert '<img src="file:///private">' in text
    assert "<img " not in document.toHtml()
    assert not document.find("伪造引用").charFormat().isAnchor()
    assert not panel.math_renderer.pending


def test_finished_math_markdown_stops_refreshing_when_scrollbar_is_visible(output, qtbot):
    panel, show_answer = output
    panel.resize(360, 400)
    panel.show()
    show_answer("## 结果\n\n" + "- 一项实验结果\n" * 30 + r"\(x_i=1\)")
    qtbot.waitUntil(lambda: '<img ' in panel.answer_browser.toHtml(), timeout=15000)
    assert panel.answer_browser.verticalScrollBar().maximum() > 0
    qtbot.wait(200)
    refreshes = QSignalSpy(panel.math_renderer.ready)
    qtbot.wait(350)
    assert refreshes.count() == 0


def test_streaming_markdown_preserves_math_citation_and_raw_copy(qtbot, tmp_path):
    controller, client, loader, settings, _ = make_controller(tmp_path)
    panel = PdfQuestionPanel(settings, controller=controller)
    qtbot.addWidget(panel)
    try:
        panel.question_input.setPlainText("Explain")
        panel.send_button.click()
        loader.loaded.emit(("First page",))
        client.partial.emit(1, "**结论")
        qtbot.waitUntil(lambda: "结论" in panel.answer_browser.toPlainText())
        answer = r"**结论：\(x_i=1\)，见[第 1 页｜First page]。**"
        client.completed.emit(1, answer)
        qtbot.waitUntil(lambda: '<img ' in panel.answer_browser.toHtml(), timeout=15000)
        document = panel.answer_browser.document()
        assert document.find("结论").charFormat().fontWeight() >= QFont.Weight.Bold
        assert document.find("[第 1 页]").charFormat().anchorHref() == "pdf-citation:0"
        assert panel._citation_quote("pdf-citation:0") == "First page"
        panel.copy_button.click()
        assert QApplication.clipboard().text() == answer
    finally:
        panel.dispose()
