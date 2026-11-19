import json
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QPainter, QPdfWriter, QWheelEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from learning_assistant.ui.pdf_reader_window import PdfReaderWindow
from tests_v2.test_pdf_tabs import FakePdfController, _settings
from tests_v2.test_pdf_render_lifecycle import reader, _select_first_line
from tests_v2.test_pdfjs_view import _run_javascript


@pytest.fixture
def scroll_reader(qtbot, tmp_path):
    pdf = tmp_path / "scroll.pdf"
    writer = QPdfWriter(str(pdf))
    painter = QPainter(writer)
    painter.setFont(QFont("Arial", 14))
    for page in range(3):
        if page:
            writer.newPage()
        for line in range(20):
            painter.drawText(1000, 1000+line*500, f"Page {page+1} line {line+1:02}: evidence and selection should stay stable.")
    painter.end()
    del writer
    window = PdfReaderWindow(_settings(tmp_path), FakePdfController)
    qtbot.addWidget(window)
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()
    try:
        assert window.open_file(pdf)
        tab = window.current_tab()
        view = tab.pdf_view
        qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
            "document.querySelectorAll('.textLayer span').length >= 20")), timeout=15000)
        view.setFocus()
        yield window, tab, view
    finally:
        window.close_all_tabs()


def _scroll_with_wheel(qtbot, view, point):
    _run_javascript(qtbot, view, """
        (() => {
            const container = document.querySelector('#viewerContainer');
            const trace = window.wheelTrace = {positions: [container.scrollTop], settled: false};
            const sample = () => trace.positions.push(container.scrollTop);
            container.addEventListener('scroll', sample);
            container.addEventListener('scrollend', () => {
                container.removeEventListener('scroll', sample);
                trace.settled = true;
            }, {once: true});
        })()
    """)
    target = view.focusProxy() or view
    wheel = QWheelEvent(
        QPointF(point), QPointF(target.mapToGlobal(point)), QPoint(), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(target, wheel)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view, "wheelTrace.settled")), timeout=2000)
    return json.loads(_run_javascript(qtbot, view, "JSON.stringify(wheelTrace.positions)"))


def test_mouse_wheel_scrolls_through_intermediate_positions(scroll_reader, qtbot):
    _, _, view = scroll_reader
    positions = _scroll_with_wheel(qtbot, view, QPoint(150, 300))
    assert any(positions[0] < offset < positions[-1] for offset in positions), positions


@pytest.mark.parametrize("release_at", ["sidebar", "next_wheel"])
def test_finishing_drag_stops_native_autoscroll_and_keeps_selection(scroll_reader, qtbot, release_at):
    _, tab, view = scroll_reader
    _run_javascript(qtbot, view, "document.querySelector('#viewerContainer').scrollTop=100")
    points = json.loads(_run_javascript(qtbot, view, """
        (()=>{const span=[...document.querySelectorAll('.page[data-page-number="1"] .textLayer span')][5];
            const rect=span.getBoundingClientRect();return JSON.stringify([rect.left+12,rect.top+rect.height/2]);})()
    """))
    target = view.focusProxy() or view
    origin = QPoint(round(points[0]), round(points[1]))
    end = QPoint(origin.x()+120, view.height()+45)
    qtbot.mousePress(target, Qt.LeftButton, pos=origin)
    for step in range(1, 9):
        qtbot.mouseMove(target, pos=origin+(end-origin)*step/8)
        qtbot.wait(20)
    wheel_point = QPoint(150, 300)
    if release_at == "sidebar":
        qtbot.mouseRelease(tab.source, Qt.LeftButton, pos=tab.source.rect().center())
    else:
        # The OS may release outside the application. A later wheel event with
        # no pressed button must recover even if Qt never saw that release.
        _scroll_with_wheel(qtbot, view, wheel_point)
    qtbot.waitUntil(lambda: tab.controller.selection is not None, timeout=2000)
    qtbot.wait(150)
    position = lambda: _run_javascript(qtbot, view, "document.querySelector('#viewerContainer').scrollTop")
    stable = position()
    qtbot.wait(300)
    assert position() == pytest.approx(stable, abs=1)
    _scroll_with_wheel(qtbot, view, wheel_point)
    after_wheel = position()
    assert after_wheel > stable
    qtbot.wait(300)
    assert position() == pytest.approx(after_wheel, abs=1)
    if release_at == "next_wheel":
        # Balance QTest's simulated button state after verifying recovery.
        qtbot.mouseRelease(target, Qt.LeftButton, pos=wheel_point)


def test_blur_before_mouseup_commits_current_pdf_selection(reader, qtbot):
    _, tab, view = reader
    _run_javascript(qtbot, view, """
        (()=>{const span=document.querySelector('.textLayer span'), range=document.createRange();
            range.selectNodeContents(span);window.getSelection().removeAllRanges();window.getSelection().addRange(range);
            window.dispatchEvent(new Event('blur'));})()
    """)
    qtbot.waitUntil(lambda: tab.controller.selection is not None, timeout=1500)
    assert tab.controller.selection.text == "First visual line"
    assert tab.highlight_button.isEnabled()


def test_repeated_mouseup_does_not_reset_the_same_committed_selection(reader, qtbot):
    _, tab, view = reader
    _select_first_line(qtbot, tab, view)
    changes = QSignalSpy(view.selection_changed)
    _run_javascript(qtbot, view, "document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))")
    qtbot.wait(100)
    assert changes.count() == 0
    assert tab.controller.selection.text == "First visual line"


def test_selection_bounds_exclude_pdfjs_full_page_end_marker(reader, qtbot):
    _, tab, view = reader
    _run_javascript(qtbot, view, """
        (()=>{const layer=document.querySelector('.textLayer'), marker=layer.querySelector('.endOfContent');
            marker.style.width='600px';marker.style.height='800px';marker.style.top='0px';
            const range=document.createRange();range.selectNodeContents(layer);
            window.getSelection().removeAllRanges();window.getSelection().addRange(range);
            document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));})()
    """)
    qtbot.waitUntil(lambda: tab.controller.selection is not None)
    assert tab.controller.selection.can_annotate
    assert len(tab.controller.selection.bounds) >= 3
    assert all(height < 50 for _, _, _, height in tab.controller.selection.bounds)
