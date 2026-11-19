from learning_assistant.domain.pdf_models import PdfAnnotation
import json
import pytest
from tests_v2.test_pdf_render_lifecycle import reader, _select_first_line
from tests_v2.test_pdfjs_view import _run_javascript


def test_citation_highlights_exact_text_without_changing_selection_or_saved_marks(reader, qtbot):
    _, tab, view = reader
    _select_first_line(qtbot, tab, view)
    before = tab.controller.selection
    saved = PdfAnnotation(1, view.document_key, 0, before.start_index, before.end_index,
                          before.text, "green", before.bounds, 0)
    view.set_annotations([saved])
    assert view.reveal_citation(0, "Second visual line")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation-layer .linguaspark-citation'))")), timeout=5000)
    bounds_match = _run_javascript(qtbot, view, """
        (() => {
            const span = [...document.querySelectorAll('.textLayer span')].find(x => x.textContent === 'Second visual line');
            const mark = document.querySelector('.linguaspark-citation');
            const a = span.getBoundingClientRect(), b = mark.getBoundingClientRect();
            return Math.abs(a.left - b.left) < 3 && Math.abs(a.top - b.top) < 3 && Math.abs(a.width - b.width) < 3;
        })()
    """)
    assert bounds_match
    assert tab.controller.selection == before
    assert view._annotations == [saved]
    assert _run_javascript(qtbot, view, "window.getSelection().toString()") == before.text
    qtbot.waitUntil(lambda: not _run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation-layer, .linguaspark-citation-page'))"), timeout=7000)
    assert _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-annotation'))")


def test_unmatched_or_page_only_citation_marks_page_without_false_text_highlight(reader, qtbot):
    _, _, view = reader
    assert view.reveal_citation(0, "Text absent from PDF")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.page.linguaspark-citation-page'))")), timeout=5000)
    assert not _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-citation'))")
    assert view.reveal_citation(0, "")
    assert not view.reveal_citation(-1, "Second visual line")


def test_citation_matches_across_text_spans_and_realigns_after_zoom(reader, qtbot):
    _, _, view = reader
    assert view.reveal_citation(0, "SECOND visual line\nThird visual line")
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view,
        "document.querySelectorAll('.linguaspark-citation').length") >= 2, timeout=5000)
    view.set_zoom_factor(1.4)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view, """
        (() => {
            if (PDFViewerApplication.pdfViewer.currentScale !== 1.4 ||
                PDFViewerApplication.pdfViewer.getPageView(0).renderingState !== 3) return false;
            const mark = document.querySelector('.linguaspark-citation');
            const span = [...document.querySelectorAll('.textLayer span')].find(x => x.textContent === 'Second visual line');
            if (!mark || !span) return false;
            const a = span.getBoundingClientRect(), b = mark.getBoundingClientRect();
            return Math.abs(a.left - b.left) < 3 && Math.abs(a.top - b.top) < 3;
        })()
    """)), timeout=5000)
    _run_javascript(qtbot, view, "document.querySelector('.page').dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, button:0}))")
    assert not _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-citation'))")


def test_ambiguous_citation_uses_page_cue_and_new_citation_replaces_old_one(reader, qtbot):
    _, _, view = reader
    assert view.reveal_citation(0, "visual line")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation-page'))")))
    assert not _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-citation'))")
    assert view.reveal_citation(0, "First visual line")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation'))")))
    assert view.reveal_citation(0, "Not in document")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation-page'))")))
    assert not _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-citation'))")


def test_fragmented_formula_marks_merge_per_line_without_crossing_columns(reader, qtbot):
    _, _, view = reader
    bounds = ((10, 10, 12, 18), (21, 10, 10, 18), (30, 19, 6, 10),
              (200, 10, 20, 18), (10, 55, 20, 18))
    view.set_annotations([PdfAnnotation(1, view.document_key, 0, 0, 10, "Formula", "yellow", bounds, 0)])
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view, "document.querySelectorAll('.linguaspark-annotation').length") > 0)
    assert _run_javascript(qtbot, view, "document.querySelectorAll('.linguaspark-annotation').length") == 3


def test_nested_formula_glyph_rectangles_do_not_stack_citation_opacity(reader, qtbot):
    _, _, view = reader
    _run_javascript(qtbot, view, """
        (() => {
            const span = document.querySelector('.textLayer span');
            const text = span.textContent;
            span.textContent = '';
            for (const character of text) {
                const child = document.createElement('span');
                child.style.cssText = 'position:relative;display:inline;font-size:1em';
                child.textContent = character;
                span.appendChild(child);
            }
        })()
    """)
    assert view.reveal_citation(0, "First visual line")
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view, "document.querySelectorAll('.linguaspark-citation').length") > 0)
    assert _run_javascript(qtbot, view, "document.querySelectorAll('.linguaspark-citation').length") == 1


@pytest.mark.parametrize("quote", ['"Second visual line"', '“Second visual line”'])
def test_citation_accepts_quotation_wrappers_without_changing_the_evidence(reader, qtbot, quote):
    _, _, view = reader
    assert view.reveal_citation(0, quote)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation'))")), timeout=5000)


def test_visible_citation_keeps_zoom_and_both_scroll_positions(reader, qtbot):
    _, _, view = reader
    view.set_zoom_factor(2.0)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "PDFViewerApplication.pdfViewer.currentScale === 2 && !document.querySelector('.textLayer').hidden")), timeout=8000)
    before = json.loads(_run_javascript(qtbot, view, """
        (() => {
            const container = document.querySelector('#viewerContainer');
            container.scrollLeft = 110;
            container.scrollTop = 40;
            return JSON.stringify({x:container.scrollLeft,y:container.scrollTop,scale:PDFViewerApplication.pdfViewer.currentScale});
        })()
    """))
    assert before["x"] > 0 and before["y"] > 0
    assert view.reveal_citation(0, "Second visual line")
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.linguaspark-citation'))")), timeout=5000)
    after = json.loads(_run_javascript(qtbot, view, """
        JSON.stringify({x:document.querySelector('#viewerContainer').scrollLeft,
                        y:document.querySelector('#viewerContainer').scrollTop,
                        scale:PDFViewerApplication.pdfViewer.currentScale})
    """))
    assert after == before


def _write_citation_pdf(path, two_pages=False):
    from PySide6.QtGui import QPainter, QPdfWriter
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(1000, 200, "The reader's multi-")
    painter.drawText(1000, 500, "line evidence proves this point.")
    if two_pages:
        writer.newPage()
        painter.drawText(3500, 200, "Second page supporting evidence")
    painter.end()
    del writer


def test_citation_matches_smart_punctuation_and_a_word_hyphenated_across_pdf_lines(reader, qtbot, tmp_path):
    _, tab, view = reader
    pdf = tmp_path / "hyphenated.pdf"
    _write_citation_pdf(pdf)
    assert tab.load_file(pdf)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "document.querySelector('.textLayer')?.textContent.includes('multi-')")), timeout=15000)
    assert view.reveal_citation(0, '“The reader’s multiline evidence proves this point.”')
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view,
        "document.querySelectorAll('.linguaspark-citation').length") >= 2, timeout=8000)


def test_cross_page_citation_preserves_pan_and_survives_page_change_notification(reader, qtbot, tmp_path):
    _, tab, view = reader
    pdf = tmp_path / "two-pages.pdf"
    _write_citation_pdf(pdf, two_pages=True)
    assert tab.load_file(pdf)
    qtbot.waitUntil(lambda: _run_javascript(qtbot, view,
        "globalThis.PDFViewerApplication?.pdfDocument?.numPages") == 2, timeout=15000)
    view.set_zoom_factor(2)
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "PDFViewerApplication.pdfViewer.currentScale === 2 && !document.querySelector('.textLayer').hidden")), timeout=8000)
    pan = _run_javascript(qtbot, view,
        "document.querySelector('#viewerContainer').scrollLeft=110; document.querySelector('#viewerContainer').scrollLeft")
    assert pan > 0
    assert view.reveal_citation(1, '"Second page supporting evidence"')
    qtbot.waitUntil(lambda: bool(_run_javascript(qtbot, view,
        "Boolean(document.querySelector('.page[data-page-number=\"2\"] .linguaspark-citation'))")), timeout=8000)
    assert _run_javascript(qtbot, view, "document.querySelector('#viewerContainer').scrollLeft") == pan
    assert view.zoomFactor() == 2
    _run_javascript(qtbot, view, "PDFViewerApplication.eventBus.dispatch('pagechanging',{pageNumber:1})")
    assert _run_javascript(qtbot, view, "Boolean(document.querySelector('.linguaspark-citation'))")
