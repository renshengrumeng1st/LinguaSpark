from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtPdfWidgets import QPdfView


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
