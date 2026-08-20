from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtTest import QSignalSpy

from learning_assistant.domain.pdf_models import PdfAnnotation, PdfTextSelection
from learning_assistant.ui.pdfjs_view import PdfJsViewAdapter


def _write_three_line_pdf(path: Path) -> None:
    stream = (
        b"BT /F1 18 Tf 72 720 Td "
        b"(First visual line) Tj "
        b"0 -30 Td (Second visual line) Tj "
        b"0 -30 Td (Third visual line) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
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


def _run_javascript(qtbot, view: PdfJsViewAdapter, script: str):
    result: list[object] = []
    view.page().runJavaScript(script, result.append)
    qtbot.waitUntil(lambda: bool(result), timeout=5_000)
    return result[0]


def test_adapter_rejects_missing_and_non_pdf_files(qtbot, tmp_path: Path) -> None:
    """Invalid local input must fail before a browser or server is started."""
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)
    failures = QSignalSpy(view.load_failed)
    text_file = tmp_path / "not-a-pdf.txt"
    text_file.write_text("hello", encoding="utf-8")

    assert view.load_file(tmp_path / "missing.pdf") is False
    assert view.load_file(text_file) is False

    assert failures.count() == 2
    assert view.document_key == ""
    assert view.current_selection() is None
    assert view._server is None


def test_adapter_uses_dom_selection_and_preserves_reader_contract(
    qtbot, tmp_path: Path
) -> None:
    """Replacing the DOM text layer with reconstructed Qt bounds must fail."""
    document = tmp_path / "three-lines.pdf"
    _write_three_line_pdf(document)
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)
    view.resize(900, 760)
    loaded = QSignalSpy(view.document_loaded)
    selected = QSignalSpy(view.selection_changed)
    zoomed = QSignalSpy(view.zoomFactorChanged)

    try:
        view.show()
        assert view.load_file(document) is True
        qtbot.waitUntil(lambda: loaded.count() == 1, timeout=10_000)
        assert loaded.at(0)[1] == 1
        assert loaded.at(0)[0] == view.document_key
        qtbot.waitUntil(
            lambda: bool(
                _run_javascript(
                    qtbot,
                    view,
                    "document.querySelectorAll("
                    "'.page[data-page-number=\\\"1\\\"] .textLayer span'"
                    ").length >= 3",
                )
            ),
            timeout=20_000,
        )

        _run_javascript(
            qtbot,
            view,
            """
            (() => {
                const spans = [...document.querySelectorAll(
                    '.page[data-page-number="1"] .textLayer span'
                )].filter(span => span.textContent.trim());
                const range = document.createRange();
                range.setStart(spans[0].firstChild, 0);
                range.setEnd(spans[2].firstChild, spans[2].textContent.length);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                return true;
            })()
            """,
        )
        qtbot.waitUntil(lambda: selected.count() == 1, timeout=5_000)
        selection = selected.at(0)[0]
        assert isinstance(selection, PdfTextSelection)
        assert selection.page_index == 0
        assert selection.can_annotate is True
        assert selection.start_index == 0
        assert selection.end_index > selection.start_index
        assert "First visual line" in selection.text
        assert "Second visual line" in selection.text
        assert "Third visual line" in selection.text
        assert len(selection.bounds) >= 3

        view.set_zoom_factor(1.5)
        qtbot.waitUntil(lambda: view.zoomFactor() == pytest.approx(1.5), timeout=8_000)
        assert zoomed.count() >= 1
        assert view.zoomMode() == QPdfView.ZoomMode.Custom

        view.fit_to_width()
        qtbot.waitUntil(
            lambda: _run_javascript(
                qtbot,
                view,
                "globalThis.PDFViewerApplication?.pdfViewer?.currentScaleValue || ''",
            )
            == "page-width",
            timeout=8_000,
        )
        assert view.zoomMode() == QPdfView.ZoomMode.FitToWidth
    finally:
        view.close_document()
        view.close()


def test_theme_and_persistent_annotation_follow_pdfjs_zoom(
    qtbot, tmp_path: Path
) -> None:
    """Tint and saved marks must share PDF.js's scale instead of Python layout."""
    document = tmp_path / "annotated.pdf"
    _write_three_line_pdf(document)
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)
    view.resize(900, 760)
    loaded = QSignalSpy(view.document_loaded)

    try:
        view.show()
        view.set_reading_theme("eye_care")
        assert view.load_file(document) is True
        qtbot.waitUntil(lambda: loaded.count() == 1, timeout=10_000)
        qtbot.waitUntil(
            lambda: bool(
                _run_javascript(
                    qtbot,
                    view,
                    "Boolean(document.querySelector("
                    "'.page[data-page-number=\\\"1\\\"]'))",
                )
            ),
            timeout=10_000,
        )
        key = view.document_key
        view.set_annotations(
            [
                PdfAnnotation(
                    1,
                    key,
                    0,
                    0,
                    10,
                    "First line",
                    "yellow",
                    ((72.0, 55.0, 120.0, 18.0),),
                    0,
                )
            ]
        )
        qtbot.waitUntil(
            lambda: bool(
                _run_javascript(
                    qtbot,
                    view,
                    "Boolean(document.querySelector('.linguaspark-annotation'))",
                )
            ),
            timeout=5_000,
        )
        before = json.loads(
            _run_javascript(
                qtbot,
                view,
                """
                (() => {
                    const page = document.querySelector('.pdfViewer .page');
                    const mark = document.querySelector('.linguaspark-annotation');
                    return JSON.stringify({
                        paper: getComputedStyle(page).backgroundColor,
                        width: parseFloat(mark.style.width),
                        color: getComputedStyle(mark).backgroundColor
                    });
                })()
                """,
            )
        )
        assert before["paper"] == "rgb(234, 244, 226)"
        # PDF.js maps 72 PDF points to 96 CSS pixels at 100%.
        assert before["width"] == pytest.approx(160.0, abs=1.0)
        assert before["color"] == "rgba(250, 204, 21, 0.42)"

        view.set_zoom_factor(2.0)
        qtbot.waitUntil(
            lambda: float(
                _run_javascript(
                    qtbot,
                    view,
                    "parseFloat(document.querySelector("
                    "'.linguaspark-annotation')?.style.width || '-1')",
                )
            )
            == pytest.approx(320.0, abs=1.0),
            timeout=8_000,
        )
    finally:
        view.close_document()
        view.close()


def test_ctrl_wheel_routes_to_reader_zoom(qtbot) -> None:
    """Ctrl-wheel must change PDF scale rather than Chromium page zoom."""
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)

    view._adjust_zoom_from_wheel(120, Qt.KeyboardModifier.ControlModifier)

    assert view.zoomFactor() == pytest.approx(1.1)


def test_image_only_page_surfaces_ocr_feedback_and_clears_selection(qtbot) -> None:
    """A failed selection on an image page must explain the limitation."""
    view = PdfJsViewAdapter()
    qtbot.addWidget(view)
    feedback = QSignalSpy(view.selection_feedback)
    selections = QSignalSpy(view.selection_changed)

    view._bridge.empty(False)

    assert selections.count() == 1
    assert selections.at(0)[0] is None
    assert feedback.count() == 1
    assert feedback.at(0)[0] == "当前页面没有可选择文字，扫描版 PDF 暂不支持 OCR"
