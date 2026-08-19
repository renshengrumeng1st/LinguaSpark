from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication


def _pdf_view_module():
    assert importlib.util.find_spec("learning_assistant.ui.pdf_view") is not None, (
        "PDF reader view is missing"
    )
    return importlib.import_module("learning_assistant.ui.pdf_view")


def _write_two_page_pdf(path: Path) -> None:
    first = b"BT /F1 18 Tf 72 720 Td (First page sentence.) Tj ET"
    second = b"BT /F1 18 Tf 72 720 Td (Second page sentence.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(first), first),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(second), second),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode())
        content.extend(value)
        content.extend(b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(content)


def test_page_layout_accounts_for_scroll_and_different_page_heights() -> None:
    pdf_view = _pdf_view_module()
    layout = pdf_view.PdfPageLayout(
        [(600.0, 800.0), (500.0, 700.0)],
        zoom=1.0,
        viewport_width=900.0,
        margin=24.0,
        spacing=16.0,
    )

    hit = layout.hit_test(450.0, 850.0, scroll_y=100.0)

    assert hit is not None
    page, point = hit
    assert page == 1
    assert point.x() == pytest.approx(250.0)
    assert point.y() == pytest.approx(110.0)


def test_page_layout_maps_pdf_annotation_back_to_scrolled_viewport() -> None:
    pdf_view = _pdf_view_module()
    layout = pdf_view.PdfPageLayout(
        [(600.0, 800.0), (500.0, 700.0)],
        zoom=1.0,
        viewport_width=900.0,
        margin=24.0,
        spacing=16.0,
    )

    mapped = layout.pdf_rect_to_viewport(
        1, (10.0, 20.0, 30.0, 40.0), scroll_y=100.0
    )

    assert mapped == QRectF(210.0, 760.0, 30.0, 40.0)


def test_page_layout_scales_pdf_coordinates_with_zoom() -> None:
    pdf_view = _pdf_view_module()
    layout = pdf_view.PdfPageLayout(
        [(600.0, 800.0)],
        zoom=2.0,
        viewport_width=900.0,
        margin=24.0,
        spacing=16.0,
    )

    hit = layout.hit_test(224.0, 424.0, scroll_y=0.0)

    assert hit is not None
    page, point = hit
    assert page == 0
    assert point.x() == pytest.approx(100.0)
    assert point.y() == pytest.approx(200.0)


def test_selectable_pdf_view_loads_real_pdf_in_continuous_mode(
    qtbot,
    tmp_path: Path,
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "two-pages.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(420, 300)
        view.show()

        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)

        assert view.pageMode() == QPdfView.PageMode.MultiPage
        assert "First page sentence." in view.document().getAllText(0).text()
        assert view.verticalScrollBar().maximum() > 0
    finally:
        view.document().close()
        view.close()


def test_selectable_pdf_view_rejects_non_pdf_file(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    not_pdf = tmp_path / "broken.pdf"
    not_pdf.write_text("not a pdf", encoding="utf-8")
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    failures: list[str] = []
    view.load_failed.connect(failures.append)
    try:
        assert view.load_file(not_pdf) is False
        assert failures == ["无法打开此 PDF"]
        assert view.set_pdf_password("secret") is False
        assert failures == ["无法打开此 PDF", "无法打开此 PDF"]
    finally:
        view.document().close()
        view.close()


def test_continuous_scroll_reports_second_page(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "scroll-pages.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    pages: list[int] = []
    view.current_page_changed.connect(pages.append)
    try:
        view.resize(420, 300)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)

        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())

        qtbot.waitUntil(lambda: bool(pages) and pages[-1] == 1)
    finally:
        view.document().close()
        view.close()


def test_overlay_layout_matches_qt_pdf_scroll_extents(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "layout-pages.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(420, 300)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
        layout = view._layout()

        assert layout.content_width == pytest.approx(
            view.horizontalScrollBar().maximum() + view.viewport().width(), abs=1
        )
        assert layout.content_height == pytest.approx(
            view.verticalScrollBar().maximum() + view.viewport().height(), abs=1
        )
    finally:
        view.document().close()
        view.close()


def test_mouse_drag_extracts_text_from_real_pdf(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "select-text.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        start = layout.pdf_rect_to_viewport(0, (74, 64, 1, 1), 0).center().toPoint()
        end = layout.pdf_rect_to_viewport(0, (233, 70, 1, 1), 0).center().toPoint()

        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view.viewport(), pos=end)
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

        assert view.current_selection() is not None
        assert "First page sentence." in view.current_selection().text
    finally:
        view.document().close()
        view.close()


def test_drag_near_text_snaps_and_previews_before_release(
    qtbot, tmp_path: Path
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "snap-near-text.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    final_selections = QSignalSpy(view.selection_changed)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        start = layout.pdf_rect_to_viewport(0, (66, 55, 1, 1), 0).center().toPoint()
        end = layout.pdf_rect_to_viewport(0, (241, 80, 1, 1), 0).center().toPoint()

        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view.viewport(), pos=end)

        assert view.current_selection() is not None
        assert "First page sentence." in view.current_selection().text
        assert final_selections.count() == 0

        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

        assert final_selections.count() == 1
    finally:
        view.document().close()
        view.close()


def test_hover_cursor_only_becomes_ibeam_near_pdf_text(
    qtbot, tmp_path: Path
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "hover-cursor.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        near = layout.pdf_rect_to_viewport(0, (66, 55, 1, 1), 0).center().toPoint()
        far = layout.pdf_rect_to_viewport(0, (350, 350, 1, 1), 0).center().toPoint()

        near_event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(near),
            QPointF(view.viewport().mapToGlobal(near)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.viewport(), near_event)
        assert view.viewport().cursor().shape() == Qt.CursorShape.IBeamCursor

        far_event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(far),
            QPointF(view.viewport().mapToGlobal(far)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.viewport(), far_event)
        assert view.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        view.document().close()
        view.close()


def test_drag_far_from_pdf_text_does_not_create_selection(
    qtbot, tmp_path: Path
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "far-from-text.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    final_selections = QSignalSpy(view.selection_changed)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        start = layout.pdf_rect_to_viewport(0, (350, 350, 1, 1), 0).center().toPoint()
        end = layout.pdf_rect_to_viewport(0, (450, 420, 1, 1), 0).center().toPoint()

        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view.viewport(), pos=end)
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

        assert view.current_selection() is None
        assert final_selections.count() == 0
    finally:
        view.document().close()
        view.close()


def test_drag_started_on_text_can_finish_beyond_line_end(
    qtbot, tmp_path: Path
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "beyond-line-end.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        start = layout.pdf_rect_to_viewport(0, (74, 64, 1, 1), 0).center().toPoint()
        end = layout.pdf_rect_to_viewport(0, (300, 105, 1, 1), 0).center().toPoint()

        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view.viewport(), pos=end)
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

        assert view.current_selection() is not None
        assert "First page sentence." in view.current_selection().text
    finally:
        view.document().close()
        view.close()


def test_eye_care_theme_recolors_the_pdf_paper(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "eye-care-paper.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        view.set_reading_theme("eye_care")
        qtbot.wait(50)
        point = view._layout().pdf_rect_to_viewport(
            0, (350, 350, 1, 1), 0
        ).center().toPoint()
        image = view.viewport().grab().toImage()
        dpr = image.devicePixelRatio()
        physical_point = QPoint(round(point.x() * dpr), round(point.y() * dpr))
        paper = image.pixelColor(physical_point)

        assert paper.red() == pytest.approx(234, abs=3)
        assert paper.green() == pytest.approx(244, abs=3)
        assert paper.blue() == pytest.approx(226, abs=3)
    finally:
        view.document().close()
        view.close()


def test_selected_sentence_has_a_visible_blue_overlay(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "blue-selection.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(1000, 500)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.document().pageCount() == 2)
        layout = view._layout()
        start = layout.pdf_rect_to_viewport(0, (74, 64, 1, 1), 0).center().toPoint()
        end = layout.pdf_rect_to_viewport(0, (233, 70, 1, 1), 0).center().toPoint()
        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view.viewport(), pos=end)
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        qtbot.wait(20)

        image = view.viewport().grab().toImage()
        selection = view.current_selection()
        assert selection is not None
        rect = layout.pdf_rect_to_viewport(0, selection.bounds[0], 0).toRect()
        dpr = image.devicePixelRatio()
        blue_pixels = [
            image.pixelColor(x, y)
            for y in range(
                max(0, round(rect.top() * dpr)),
                min(image.height(), round((rect.bottom() + 1) * dpr)),
            )
            for x in range(
                max(0, round(rect.left() * dpr)),
                min(image.width(), round((rect.right() + 1) * dpr)),
            )
        ]
        assert any(
            color.red() < 150 and color.blue() > 180
            for color in blue_pixels
        )
    finally:
        view.document().close()
        view.close()


def test_ctrl_wheel_changes_zoom_without_turning_pages(qtbot) -> None:
    pdf_view = _pdf_view_module()
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    event = QWheelEvent(
        QPointF(100, 100),
        QPointF(100, 100),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    view.wheelEvent(event)

    assert view.zoomFactor() == pytest.approx(1.1)
    assert event.isAccepted()


def test_opening_another_pdf_resets_zoom_to_100_percent(
    qtbot, tmp_path: Path
) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "reset-zoom.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    view.set_zoom_factor(2.0)

    assert view.load_file(document_path) is True

    assert view.zoomMode() == QPdfView.ZoomMode.Custom
    assert view.zoomFactor() == pytest.approx(1.0)
    view.document().close()


def test_zoom_keeps_the_current_pdf_page(qtbot, tmp_path: Path) -> None:
    pdf_view = _pdf_view_module()
    document_path = tmp_path / "keep-page.pdf"
    _write_two_page_pdf(document_path)
    view = pdf_view.SelectablePdfView()
    qtbot.addWidget(view)
    try:
        view.resize(420, 300)
        view.show()
        assert view.load_file(document_path) is True
        qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        qtbot.waitUntil(lambda: view.pageNavigator().currentPage() == 1)

        view.set_zoom_factor(1.5)

        qtbot.waitUntil(lambda: view.pageNavigator().currentPage() == 1)
        assert view.zoomFactor() == pytest.approx(1.5)
    finally:
        view.document().close()
        view.close()
