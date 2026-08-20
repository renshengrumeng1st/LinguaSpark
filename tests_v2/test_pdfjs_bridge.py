from __future__ import annotations

import json

from PySide6.QtTest import QSignalSpy

from learning_assistant.domain.pdf_models import PdfTextSelection
from learning_assistant.ui.pdfjs_bridge import PdfJsBridge


def test_bridge_turns_a_single_page_dom_selection_into_stable_pdf_selection(
    qtbot,
) -> None:
    """Dropping normalized text, stable indices, or any visual line is a bug."""
    bridge = PdfJsBridge()
    selected = QSignalSpy(bridge.selection_changed)

    bridge.commit(
        json.dumps(
            {
                "text": "A hyphen-\nated first line\nSecond line",
                "pages": [2],
                "page": 2,
                "start": 41,
                "end": 78,
                "rects": [
                    {"page": 2, "x": 12.5, "y": 24.0, "width": 80.0, "height": 14.0},
                    {"page": 2, "x": 12.5, "y": 40.0, "width": 65.0, "height": 13.5},
                ],
            }
        )
    )

    assert selected.count() == 1
    assert selected.at(0)[0] == PdfTextSelection(
        page_index=2,
        start_index=41,
        end_index=78,
        text="A hyphenated first line Second line",
        bounds=(
            (12.5, 24.0, 80.0, 14.0),
            (12.5, 40.0, 65.0, 13.5),
        ),
        can_annotate=True,
    )


def test_bridge_keeps_cross_page_text_translatable_but_not_annotatable(
    qtbot,
) -> None:
    """A cross-page selection must never create a misleading one-page mark."""
    bridge = PdfJsBridge()
    selected = QSignalSpy(bridge.selection_changed)

    bridge.commit(
        json.dumps(
            {
                "text": "End of page one. Start of page two.",
                "pages": [0, 1],
                "page": 0,
                "start": 120,
                "end": 157,
                "rects": [
                    {"page": 0, "x": 10, "y": 700, "width": 90, "height": 12},
                    {"page": 1, "x": 10, "y": 20, "width": 100, "height": 12},
                ],
            }
        )
    )

    selection = selected.at(0)[0]
    assert selection.text == "End of page one. Start of page two."
    assert selection.page_index == 0
    assert selection.bounds == ((10.0, 700.0, 90.0, 12.0),)
    assert selection.can_annotate is False


def test_bridge_clears_empty_selection_and_rejects_non_finite_geometry(qtbot) -> None:
    """Empty or unsafe browser payloads must not reach translation or storage."""
    bridge = PdfJsBridge()
    selected = QSignalSpy(bridge.selection_changed)
    failures = QSignalSpy(bridge.bridge_error)

    bridge.commit('{"text":"   ","pages":[],"rects":[]}')
    bridge.commit(
        '{"text":"unsafe","pages":[0],"page":0,"start":0,"end":6,'
        '"rects":[{"page":0,"x":1e999,"y":0,"width":10,"height":10}]}'
    )

    assert selected.count() == 1
    assert selected.at(0)[0] is None
    assert failures.count() == 1
    assert "invalid PDF.js selection" in failures.at(0)[0]


def test_bridge_reports_whether_an_empty_page_has_selectable_text(qtbot) -> None:
    """An image-only page needs OCR feedback instead of a silent no-op."""
    bridge = PdfJsBridge()
    empty = QSignalSpy(bridge.empty_selection)

    bridge.empty(False)

    assert empty.count() == 1
    assert empty.at(0)[0] is False
