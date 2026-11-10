"""Exercise selection and rendering transitions against the real PDF.js viewer."""

import json

import pytest
from PySide6.QtCore import QPoint, QRect, Qt

from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
from tests_v2.test_pdf_tabs import FakePdfController, _settings
from tests_v2.test_pdfjs_view import _run_javascript, _write_three_line_pdf


@pytest.fixture
def reader(qtbot, tmp_path):
    document = tmp_path / "lifecycle.pdf"
    _write_three_line_pdf(document)
    window = PdfReaderWindow(_settings(tmp_path), FakePdfController)
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    assert window.open_file(document)
    tab = window.current_tab()
    view = tab.pdf_view
    try:
        qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view, """
            document.querySelector('.page .textLayer span')?.getBoundingClientRect().width > 0
                && PDFViewerApplication.pdfViewer.getPageView(0).renderingState === 3
        """)), timeout=15000)
        view.setFocus()
        qtbot.waitUntil(view.hasFocus)
        yield window, tab, view
    finally:
        window.close_all_tabs()


def _select_first_line(qtbot, tab, view):
    _run_javascript(qtbot, view, """
        (() => {
            const span = document.querySelector('.page .textLayer span');
            const range = document.createRange();
            range.selectNodeContents(span);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        })()
    """)
    qtbot.waitUntil(lambda: tab.controller.selection is not None)


def _assert_no_black_frame(view):
    image = view.grab().toImage()
    colors = [image.pixelColor(x, y)
              for y in range(8, image.height(), 24)
              for x in range(8, image.width(), 24)]
    assert colors
    # The fixture has three lines on pale paper, never a large dark region.
    assert sum(max(c.red(), c.green(), c.blue()) < 30 for c in colors) / len(colors) < 0.2


def test_clicking_sidebar_removes_visual_selection_but_keeps_actions(reader, qtbot):
    _, tab, view = reader
    _select_first_line(qtbot, tab, view)
    selection = tab.controller.selection
    bounds = json.loads(_run_javascript(qtbot, view, """
        (() => {
            const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
            return JSON.stringify([rect.left, rect.top, rect.width, rect.height]);
        })()
    """))
    region = QRect(*(round(value) for value in bounds))
    def blue_pixels():
        image = view.grab(region).toImage()
        return sum(color.blue() > color.red() + 30 and color.blue() > color.green() + 10
                   for y in range(0, image.height(), 2)
                   for x in range(0, image.width(), 2)
                   for color in (image.pixelColor(x, y),))
    qtbot.waitUntil(lambda: blue_pixels() > 5, timeout=1500)

    qtbot.mouseClick(tab.source, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: _run_javascript(qtbot, view,
        "window.getSelection().toString()") == "", timeout=1000)
    qtbot.waitUntil(lambda: blue_pixels() == 0, timeout=1500)
    assert tab.controller.selection == selection
    assert tab.highlight_button.isEnabled()
    assert tab.translate_button.isEnabled()


def test_focus_change_does_not_let_pending_mouseup_clear_action_text(reader, qtbot):
    _, tab, view = reader
    _select_first_line(qtbot, tab, view)
    selection = tab.controller.selection
    _run_javascript(qtbot, view, """
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        window.dispatchEvent(new Event('blur'));
    """)
    # A queued report must see the retained action selection after focus moves.
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view,
        "window.getSelection().toString()") == "")
    assert tab.controller.selection == selection


@pytest.mark.parametrize("clear_method", ["script", "blank_click"])
def test_collapsed_browser_selection_clears_reader_state(reader, qtbot, clear_method):
    _, tab, view = reader
    _select_first_line(qtbot, tab, view)
    if clear_method == "script":
        _run_javascript(qtbot, view, "window.getSelection().removeAllRanges();")
    else:
        point = json.loads(_run_javascript(qtbot, view, """
            (() => {
                const bounds = document.querySelector('.page').getBoundingClientRect();
                return JSON.stringify([bounds.left + 20, bounds.top + 240]);
            })()
        """))
        qtbot.mouseClick(view.focusProxy() or view, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(point[0]), round(point[1])))
    qtbot.waitUntil(lambda: tab.controller.selection is None, timeout=1000)
    assert not tab.highlight_button.isEnabled()
    assert _run_javascript(qtbot, view, "window.getSelection().toString()") == ""


def test_rapid_zoom_keeps_the_last_drawn_canvas_until_redraw(reader, qtbot):
    _, _, view = reader
    _run_javascript(qtbot, view, """
        (() => {
            const page = PDFViewerApplication.pdfViewer.getPageView(0).pdfPage;
            const render = page.render;
            globalThis.zoomRenderStarts = 0;
            globalThis.zoomBurstDone = false;
            page.render = function(...args) {
                globalThis.zoomRenderStarts++;
                return render.apply(this, args);
            };
            const scales = [1.2, 1.4, 1.6];
            const next = () => {
                linguaReader.setZoomFactor(scales.shift());
                if (scales.length) setTimeout(next, 16);
                else globalThis.zoomBurstDone = true;
            };
            next();
        })()
    """)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view, "globalThis.zoomBurstDone")))
    assert _run_javascript(qtbot, view, "globalThis.zoomRenderStarts") <= 1, (
        "Each wheel tick starts a fresh canvas render instead of keeping the last frame"
    )
    _assert_no_black_frame(view)
    result = json.loads(_run_javascript(qtbot, view, """
        (() => {
            const previous = document.querySelector('.page canvas');
            linguaReader.setZoomFactor(1.2);
            linguaReader.setZoomFactor(1.4);
            linguaReader.setZoomFactor(1.6);
            return JSON.stringify({retained: previous.isConnected && previous.width > 0});
        })()
    """))
    assert result["retained"], "Zoom discarded the last frame before its replacement was drawn"
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view, """
        PDFViewerApplication.pdfViewer.currentScale === 1.6
            && PDFViewerApplication.pdfViewer.getPageView(0).renderingState === 3
            && !document.querySelector('.textLayer').hidden
    """)), timeout=8000)
    _assert_no_black_frame(view)


@pytest.mark.parametrize("maximized", [False, True])
def test_focus_round_trip_restores_window_and_keeps_pdf_visible(reader, qtbot, maximized):
    window, tab, view = reader
    if maximized:
        window.showMaximized()
        qtbot.waitUntil(lambda: window.isMaximized()
                       and window.width() >= window.screen().availableGeometry().width())
    else:
        assert not window.isMaximized()
    before_size = window.size()
    tab.translation.setPlainText("Keep this translation")
    for cycle in range(2):
        state_before = window.windowState()
        window.enter_focus_mode()
        qtbot.waitUntil(lambda: window.isFullScreen()
                       and window.size() == window.screen().geometry().size())
        _assert_no_black_frame(view)
        qtbot.waitUntil(view._viewport_preview.isHidden, timeout=2000)
        _assert_no_black_frame(view)
        window.exit_focus_mode()
        qtbot.waitUntil(lambda: not window.isFullScreen()
                       and window.isMaximized() == maximized)
        assert window.isMaximized() == maximized, (
            cycle, state_before, window._pre_focus_state, window.windowState(),
            window.size(), before_size,
        )
        qtbot.waitUntil(lambda: window.size() == before_size)
        qtbot.waitUntil(view._viewport_preview.isHidden, timeout=2000)
        assert tab.translation.toPlainText() == "Keep this translation"
        assert window.current_tab() is tab
        _assert_no_black_frame(view)


def test_old_viewport_ack_cannot_remove_newer_transition_preview(reader, qtbot):
    _, _, view = reader
    view.begin_viewport_transition()
    old_generation = view._viewport_generation
    view.begin_viewport_transition()
    view._viewport_frame_ready(old_generation)
    assert not view._viewport_preview.isHidden()
    qtbot.waitUntil(view._viewport_preview.isHidden, timeout=2000)
    _assert_no_black_frame(view)


def test_dragging_translation_splitter_protects_pdf_before_it_resizes(reader, qtbot):
    _, tab, view = reader
    tab.translation.setPlainText("Keep the translation while resizing")
    handle = tab.splitter.handle(1)
    origin = handle.rect().center()
    initial_width = view.width()

    qtbot.mousePress(handle, Qt.MouseButton.LeftButton, pos=origin)
    assert not view._viewport_preview.isHidden(), "Splitter drag started without a complete PDF frame"
    for distance in (-80, -140, 40, 90):
        qtbot.mouseMove(handle, pos=origin + QPoint(distance, 0))
        assert not view._viewport_preview.isHidden()
        _assert_no_black_frame(view)
        image = view.grab().toImage()
        # A thin strip at the newly exposed PDF edge would be missed by the
        # whole-frame black-area limit used for fullscreen transitions.
        edge = [image.pixelColor(x, y)
                for x in range(max(0, image.width() - 20), image.width() - 2, 2)
                for y in range(10, image.height() - 10, 12)]
        assert edge
        assert sum(max(c.red(), c.green(), c.blue()) < 30 for c in edge) / len(edge) < 0.02
    qtbot.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=origin + QPoint(90, 0))
    assert view.width() != initial_width
    qtbot.waitUntil(view._viewport_preview.isHidden, timeout=2000)
    _assert_no_black_frame(view)
    assert tab.translation.toPlainText() == "Keep the translation while resizing"

    # Dragging again after a pause must prepare another frame, rather than
    # depending on the preview that was released after the previous drag.
    qtbot.mousePress(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
    assert not view._viewport_preview.isHidden()
    qtbot.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
    qtbot.waitUntil(view._viewport_preview.isHidden, timeout=2000)
