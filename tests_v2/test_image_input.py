"""Image clipboard formats and the input-to-request boundary."""

import pytest
from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtGui import QImage, QColor, QPixmap

from learning_assistant.domain.models import QueryKind, SentenceResult
from learning_assistant.ui.main_window import InputEdit
from learning_assistant.ui.theme import apply_app_theme
from tests_v2.test_convenience import experience  # noqa: F401


def sample_image():
    image = QImage(120, 60, QImage.Format_ARGB32)
    image.fill(QColor("transparent"))
    image.setPixelColor(30, 30, QColor("black"))
    return image


@pytest.mark.parametrize("as_pixmap", [False, True])
def test_pixel_clipboard_is_accepted_and_emits_valid_jpeg(qtbot, as_pixmap):
    edit = InputEdit()
    qtbot.addWidget(edit)
    mime = QMimeData()
    image = sample_image()
    mime.setImageData(QPixmap.fromImage(image) if as_pixmap else image)
    assert edit.canInsertFromMimeData(mime)
    with qtbot.waitSignal(edit.image_pasted) as signal:
        edit.insertFromMimeData(mime)
    encoded = signal.args[0]
    assert encoded.startswith(b"\xff\xd8")
    decoded = QImage.fromData(encoded)
    assert decoded.size() == image.size()
    assert decoded.pixelColor(0, 0).lightness() > 245


def test_copied_image_file_attaches_instead_of_inserting_path(qtbot, tmp_path):
    path = tmp_path / "测试图片.png"
    assert sample_image().save(str(path))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    edit = InputEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("请翻译图片")
    assert edit.canInsertFromMimeData(mime)
    with qtbot.waitSignal(edit.image_pasted) as signal:
        edit.insertFromMimeData(mime)
    assert not QImage.fromData(signal.args[0]).isNull()
    assert edit.toPlainText() == "请翻译图片"


def test_normal_text_still_pastes(qtbot):
    edit = InputEdit()
    qtbot.addWidget(edit)
    mime = QMimeData()
    mime.setText("Hello world")
    assert edit.canInsertFromMimeData(mime)
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "Hello world"


def test_null_image_does_not_emit_empty_attachment(qtbot):
    edit = InputEdit()
    qtbot.addWidget(edit)
    mime = QMimeData()
    mime.setImageData(QImage())
    attached = []
    edit.image_pasted.connect(attached.append)
    edit.insertFromMimeData(mime)
    assert attached == []


def test_file_image_reaches_controller_and_remove_restores_text_query(experience, tmp_path):
    window, _, ai, _, _ = experience
    path = tmp_path / "input.png"
    assert sample_image().save(str(path))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    window.input.insertFromMimeData(mime)
    assert window.image_row.isVisible()
    window.submit()
    assert ai.calls[-1].kind == QueryKind.IMAGE
    assert not QImage.fromData(ai.calls[-1].image_bytes).isNull()
    window._remove_image()
    window.input.setPlainText("Hello world.")
    window.submit()
    assert ai.calls[-1].kind == QueryKind.SENTENCE
    assert ai.calls[-1].image_bytes is None


def test_invalid_attachment_keeps_existing_image(experience):
    window, _, _, _, _ = experience
    mime = QMimeData()
    mime.setImageData(sample_image())
    window.input.insertFromMimeData(mime)
    previous_image = window.image_bytes
    window._set_image(b"invalid")
    assert window.image_bytes == previous_image
    assert window.image_row.isVisible()
    assert "图片" in window.status.text()


def test_screenshot_preview_survives_resize_and_ctrl_enter_submits(qtbot, experience):
    window, _, ai, _, _ = experience
    window.input.setFocus()
    mime = QMimeData()
    mime.setImageData(sample_image())
    window.input.insertFromMimeData(mime)
    qtbot.wait(600)  # Include the entire window resize animation and debounce interval.
    assert window.image_row.isVisible()
    assert window.image_preview.isVisible()
    qtbot.keyClick(window.input, Qt.Key_Return, Qt.ControlModifier)
    assert len(ai.calls) == 1
    assert ai.calls[0].kind == QueryKind.IMAGE
    assert ai.calls[0].image_bytes == window.image_bytes


def test_different_screenshots_do_not_share_cached_translation(experience):
    _, controller, ai, _, _ = experience
    controller.submit("", image_bytes=b"first-image")
    ai.completed.emit(1, {"translation": "第一张图"}, {})
    controller.submit("", image_bytes=b"second-image")
    assert len(ai.calls) == 2
    ai.completed.emit(2, {"translation": "第二张图"}, {})
    # Repeating the same screenshot may reuse its own cached translation.
    results = []
    controller.sentence_ready.connect(lambda result, cached: results.append((result.translation, cached)))
    controller.submit("", image_bytes=b"first-image")
    assert len(ai.calls) == 2
    assert results == [("第一张图", True)]


@pytest.mark.parametrize("has_result", [False, True])
def test_image_resize_does_not_overlap_preview_and_other_sections(qtbot, qapp, experience, has_result):
    window, _, _, _, _ = experience
    previous_style = qapp.styleSheet()
    previous_palette = qapp.palette()
    previous_style_name = qapp.style().objectName()
    previous_theme = qapp.property("linguasparkTheme")
    try:
        apply_app_theme("sakura")
        if has_result:
            window.welcome.hide()
            window._on_sentence(SentenceResult(translation="上一张图的译文"), False)
        mime = QMimeData()
        mime.setImageData(sample_image())
        window.input.insertFromMimeData(mime)
        qtbot.wait(450)
        following = window.scroll if has_result else window.welcome
        assert window.input_card.geometry().bottom() < following.geometry().top()
        assert window.centralWidget().rect().contains(window.input_card.geometry())
    finally:
        qapp.setStyle(previous_style_name)
        qapp.setStyleSheet(previous_style)
        qapp.setPalette(previous_palette)
        qapp.setProperty("linguasparkTheme", previous_theme)
