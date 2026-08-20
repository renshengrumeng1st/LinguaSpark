# Qt Quick Native PDF Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-built QWidget PDF selection layer with a Qt Quick PDF scene whose page image, text selection, annotations, theme, scrolling, and zoom share one coordinate transform.

**Architecture:** Embed a project-owned Qt Quick PDF viewer in `QQuickWidget` behind a Python `QuickPdfViewAdapter` that preserves the current `PdfReaderTab` interface. QML owns visual selection and page geometry; a narrow `PdfViewBridge` converts the final QML selection into the existing domain model while the current translation, tab, shortcut, and repository layers remain unchanged.

**Tech Stack:** Python 3.14, PySide6 Essentials/Addons 6.10.1, QtQuick, QtQuick.Pdf, QtQuick.Shapes, QQuickWidget, QtPdf, pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-08-20-qt-quick-pdf-selection-design.md`

## Global Constraints

- Work only in the existing isolated worktree on local branch `feature/pdf-reader`; do not push.
- Do not run `build.bat` or create a PyInstaller artifact before user source acceptance.
- The prototype gate in Task 1 is mandatory. Do not begin Task 2 until the real problem PDF passes and the user approves the prototype.
- Reuse PySide6/Qt 6.10.1 already present in `requirements.txt`; do not add WebEngine, PDF.js, PyMuPDF, or another PDF engine.
- Keep OCR, scanned-document recognition, cross-page selection, PDF mutation, handwriting, and cloud synchronization out of scope.
- Keep multi-PDF tabs, right-side translation, phrase analysis, `Alt+W`, focus mode, local annotations, and four reading themes.
- QML must never access the LLM, SQLite, settings files, or application controllers; all non-view behavior remains in Python.
- Only the final mouse-release selection crosses the QML/Python boundary; drag previews remain inside the QML scene.
- Never use Python-derived bounds to draw the active blue selection. QML must draw `PdfSelection.geometry` directly.
- Preserve the upstream Qt copyright and license header in any copied QML file, and update `THIRD_PARTY_NOTICES.md` before completion.
- Existing uncommitted edits in `learning_assistant/ui/pdf_view.py` and `tests_v2/test_pdf_view.py` are the superseded manual-overlay experiment. Do not stage them in Tasks 1–5; Task 6 removes both files explicitly.
- Use exact-path `git add` commands so unrelated or superseded worktree changes never enter intermediate commits.
- The primary model decides delegation under `AGENTS.md`; the tasks are sequential and share one QML/Python interface, so inline execution is appropriate unless an independent review is specifically useful.

## File Structure

- `tools/qml_pdf_spike.py`: isolated, local-only viewer for testing a real PDF before production integration.
- `tools/qml/PdfSelectionSpike.qml`: minimal single-page Qt Quick selection scene used only by the feasibility gate.
- `learning_assistant/ui/pdf_themes.py`: stable theme IDs and colors shared by the tab and adapter.
- `learning_assistant/ui/pdf_view_bridge.py`: pure geometry conversion plus the single QML-to-domain selection boundary.
- `learning_assistant/ui/quick_pdf_view.py`: QWidget-compatible adapter that owns `QQuickWidget`, the indexing `QPdfDocument`, and the current selection.
- `learning_assistant/ui/qml/LinguaPdfMultiPageView.qml`: Qt 6.10.1 `PdfMultiPageView` derivative with final-selection and annotation hooks.
- `learning_assistant/ui/qml/PdfReaderView.qml`: small stable root API consumed by Python.
- `learning_assistant/ui/qml/shaders/page_tint.frag`: source for the page multiply-color effect.
- `learning_assistant/ui/qml/shaders/page_tint.frag.qsb`: precompiled Qt shader shipped with the app.
- `learning_assistant/domain/pdf_models.py`: adds explicit annotation eligibility to `PdfTextSelection` without breaking existing constructors.
- `learning_assistant/ui/pdf_reader_tab.py`: swaps the concrete view class while retaining its translation-panel behavior.
- `learning_assistant/pdf_controller.py`: rejects annotation creation when an otherwise translatable QML selection has no stable indices.
- `learning_assistant/ui/pdf_view.py`: deleted after the new viewer passes integration tests.
- `tests_v2/test_qml_pdf_spike.py`: final-pixel feasibility regression for the minimal QML scene.
- `tests_v2/test_pdf_view_bridge.py`: geometry, normalization, index extraction, and safe fallback tests.
- `tests_v2/test_quick_pdf_view.py`: production QML loading, adapter, real-PDF selection, zoom, theme, and annotation tests.
- `tests_v2/test_pdf_view.py`: deleted with the legacy view.
- `tests_v2/test_pdf_reader_ui.py` and `tests_v2/test_pdf_tabs.py`: integration regressions against the adapter rather than `QPdfView` internals.
- `build.bat`: records future PyInstaller QML collection arguments but is not executed in this plan.
- `docs/ARCHITECTURE.md`, `README.md`, and `THIRD_PARTY_NOTICES.md`: document the new boundary, user behavior, and copied Qt QML license.

---

### Task 1: Prove native QML selection on final pixels

**Files:**
- Create: `tools/qml/PdfSelectionSpike.qml`
- Create: `tools/qml_pdf_spike.py`
- Create: `tests_v2/test_qml_pdf_spike.py`

**Interfaces:**
- Produces: a throwaway `PdfSelectionSpike.qml` root with `documentSource: url`, `pageIndex: int`, `renderScale: real`, `selectionFrom: point`, `selectionTo: point`, `selectedText: string`, and `selectionGeometry: var`.
- Produces: `applySelection(real fromX, real fromY, real toX, real toY)` for deterministic pixel tests.
- Produces: `tools/qml_pdf_spike.py [--page N] [--display-scale 1.0|1.25|1.5] [path]`; without `path`, it opens a local PDF file dialog and never persists the chosen path. It sets `QT_SCALE_FACTOR` before importing PySide6 when `--display-scale` is supplied.
- Invariant: `PdfSelection.geometry` and `PdfPageImage` render in the same `paper` item and use the same `renderScale`.

- [ ] **Step 1: Write the failing QML-load and three-line pixel test**

In `tests_v2/test_qml_pdf_spike.py`, reuse a local `_write_three_line_pdf()` fixture that creates three Helvetica lines in one page. Add:

```python
def test_qml_pdf_selection_paints_every_selected_line(qtbot, tmp_path):
    path = tmp_path / "three-lines.pdf"
    _write_three_line_pdf(path)
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
    widget.resize(760, 900)
    widget.setSource(QUrl.fromLocalFile(str(SPIKE_QML)))
    widget.show()
    qtbot.waitUntil(lambda: widget.status() != QQuickWidget.Loading)
    assert widget.status() == QQuickWidget.Ready
    root = widget.rootObject()
    root.setProperty("documentSource", QUrl.fromLocalFile(str(path)))
    root.setProperty("renderScale", 1.0)
    root.setProperty("selectionFrom", QPointF(68.0, 55.0))
    root.setProperty("selectionTo", QPointF(280.0, 145.0))
    qtbot.waitUntil(lambda: "First visual line" in root.property("selectedText"))
    image = widget.grabFramebuffer()
    for y in (70, 100, 130):
        assert _row_contains_blue(image, y)
```

Add a second loop that repeats at render scales `0.5`, `1.0`, `1.5`, `2.0`, and `3.0`, recomputing sample rows from the scale. It must fail if any middle row lacks a blue pixel.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_qml_pdf_spike.py -q
```

Expected: FAIL because the spike QML and tool do not exist.

- [ ] **Step 3: Implement the minimal QML selection scene**

Create `PdfSelectionSpike.qml` with a `paper` item at `(0, 0)` whose width and height equal `pageSize * renderScale`, one page image, and one selection shape. The core must be:

```qml
PdfPageImage {
    id: image
    anchors.fill: parent
    document: doc
    currentFrame: root.pageIndex
    asynchronous: true
    sourceSize.width: pageSize.width * root.renderScale * Screen.devicePixelRatio
}

PdfSelection {
    id: selection
    anchors.fill: parent
    document: doc
    page: root.pageIndex
    renderScale: root.renderScale
    from: root.selectionFrom
    to: root.selectionTo
    hold: true
}

Shape {
    anchors.fill: parent
    ShapePath {
        strokeWidth: -1
        fillColor: "#80468FC9"
        scale: Qt.size(image.paintedWidth / pageSize.width,
                       image.paintedWidth / pageSize.width)
        PathMultiline { paths: selection.geometry }
    }
}
```

Expose `selectedText` and `selectionGeometry` aliases. `applySelection()` assigns the two point properties. Add a `DragHandler` that updates those properties so the same scene supports real mouse selection.

- [ ] **Step 4: Implement the local visual spike window**

`tools/qml_pdf_spike.py` must import `learning_assistant` before PySide6, create a `QQuickWidget`, select a file with `QFileDialog` when no path is supplied, expose zoom buttons for exactly `50%`, `100%`, `150%`, `200%`, and `300%`, and display the current selected text below the page. It must not access settings, SQLite, networking, or application controllers.

- [ ] **Step 5: Run GREEN and the existing Qt bootstrap tests**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_qml_pdf_spike.py tests_v2/test_qt_bootstrap.py -q
```

Expected: all tests pass and every selected row has blue final pixels.

- [ ] **Step 6: Execute the real-PDF visual matrix**

Run:

```powershell
..\..\.venv\Scripts\python.exe tools/qml_pdf_spike.py --page 3 --display-scale 1.0
..\..\.venv\Scripts\python.exe tools/qml_pdf_spike.py --page 3 --display-scale 1.25
..\..\.venv\Scripts\python.exe tools/qml_pdf_spike.py --page 3 --display-scale 1.5
```

Choose the existing `neural cloth simulation.pdf` in the dialog. At each zoom button, select the `Cloth subspace` paragraph, its formula-heavy continuation, a line boundary, and a double-column boundary. Save screenshots outside the repository and record whether each case has omitted rows, extra blank bands, or more than one logical pixel of drift.

- [ ] **Step 7: Commit only the spike**

```powershell
git add tools/qml/PdfSelectionSpike.qml tools/qml_pdf_spike.py tests_v2/test_qml_pdf_spike.py
git commit -m "test: prove native Qt Quick PDF selection"
```

- [ ] **Step 8: Mandatory user checkpoint**

Report the real-PDF matrix and show the screenshots. Stop here until the user explicitly approves proceeding. If any visual case fails, do not implement the production adapter; investigate the Qt Quick selection behavior or reject this architecture.

### Task 2: Define selection geometry and the Python bridge

**Files:**
- Create: `learning_assistant/ui/pdf_themes.py`
- Create: `learning_assistant/ui/pdf_view_bridge.py`
- Modify: `learning_assistant/domain/pdf_models.py`
- Create: `tests_v2/test_pdf_view_bridge.py`

**Interfaces:**
- Produces: `READING_THEMES: dict[str, str]` containing the existing four IDs and exact colors.
- Produces: `qml_geometry_to_bounds(paths: list[list[dict[str, float]]]) -> PdfBounds`.
- Produces: `PdfViewBridge(index_document: QPdfDocument)` with `selection_ready = Signal(object)` and `selection_cleared = Signal()`.
- Produces slot: `commit_selection(page: int, text: str, from_x: float, from_y: float, to_x: float, to_y: float, paths: object) -> None`. `paths` accepts either a Python list or a `QJSValue` whose `toVariant()` result is a list.
- Extends: `PdfTextSelection.can_annotate: bool = True`; all existing positional constructors remain valid.

- [ ] **Step 1: Write failing pure conversion and bridge tests**

Add tests for fragmented polygons, empty geometry, normalized text, ordered indices, and invalid index fallback:

```python
def test_bridge_keeps_qml_geometry_and_marks_stable_indices(qtbot):
    document = FakeDocument(FakeSelection(41, 73))
    bridge = PdfViewBridge(document)
    received = QSignalSpy(bridge.selection_ready)
    bridge.commit_selection(
        2, "  selected\ntext  ", 10, 20, 90, 55,
        [[{"x": 10, "y": 20}, {"x": 90, "y": 20},
          {"x": 90, "y": 30}, {"x": 10, "y": 30}]],
    )
    selection = received.at(0)[0]
    assert selection.text == "selected text"
    assert (selection.start_index, selection.end_index) == (41, 73)
    assert selection.bounds == ((10.0, 20.0, 80.0, 10.0),)
    assert selection.can_annotate is True
```

When `FakeSelection.isValid()` is false, assert text and bounds still emit, indices are `-1`, and `can_annotate` is `False`. Empty normalized text or empty paths emits `selection_cleared` and not `selection_ready`.

- [ ] **Step 2: Run RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view_bridge.py -q
```

Expected: import failures for the new modules and missing `can_annotate`.

- [ ] **Step 3: Move stable theme constants**

Create `pdf_themes.py`:

```python
READING_THEMES = {
    "eye_care": "#EAF4E2",
    "paper": "#F7F1E3",
    "soft_gray": "#EEF1F4",
    "white": "#FFFFFF",
}

HIGHLIGHT_COLORS = {
    "yellow": "#69FACC15",
    "green": "#5F4ADE80",
    "pink": "#5FF472B6",
}
```

The alpha-first strings are passed directly to QML.

- [ ] **Step 4: Implement domain compatibility and geometry conversion**

Append `can_annotate: bool = True` to `PdfTextSelection`. Add `coerce_qml_paths(value)` that calls `value.toVariant()` for a `QJSValue`, otherwise accepts a Python list, and raises `ValueError` for any other shape. `qml_geometry_to_bounds()` must reject non-finite coordinates, ignore paths with fewer than two distinct points, compute min/max extents, and preserve QML path order. It returns tuples of `(x, y, width, height)` in PDF points without line merging.

- [ ] **Step 5: Implement the one-way bridge**

Use the QML text as the translation source and `QPdfDocument.getSelection()` only for indices:

```python
candidate = self._document.getSelection(
    page, QPointF(from_x, from_y), QPointF(to_x, to_y)
)
can_annotate = candidate.isValid()
start = min(candidate.startIndex(), candidate.endIndex()) if can_annotate else -1
end = max(candidate.startIndex(), candidate.endIndex()) if can_annotate else -1
self.selection_ready.emit(PdfTextSelection(
    page, start, end, normalized, bounds, can_annotate
))
```

Do not substitute `candidate.text()` for the QML text, and do not merge or redraw the QML paths in Python.

- [ ] **Step 6: Run GREEN**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view_bridge.py tests_v2/test_domain_models.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add learning_assistant/ui/pdf_themes.py learning_assistant/ui/pdf_view_bridge.py learning_assistant/domain/pdf_models.py tests_v2/test_pdf_view_bridge.py
git commit -m "feat: define Qt Quick PDF selection bridge"
```

### Task 3: Build the production QML multipage viewer

**Files:**
- Create: `learning_assistant/ui/qml/LinguaPdfMultiPageView.qml`
- Create: `learning_assistant/ui/qml/PdfReaderView.qml`
- Create: `tests_v2/test_quick_pdf_view.py`

**Interfaces:**
- `PdfReaderView.qml` properties: `documentSource: url`, `password: string`, `zoomFactor: real`, `themeId: string`, `themeColor: color`, `annotationsByPage: var`, and read-only `currentPage: int`, `selectedText: string`.
- Signals: `selectionFinalized(int page, string text, real fromX, real fromY, real toX, real toY, var paths)`, `selectionReset()`, `pageActivated(int page)`, and `loadRejected(string message)`.
- Methods: `setZoomFactor(real factor)`, `adjustZoom(int steps)`, `fitToWidth()`, and `clearSelection()`.
- Invariant: each page delegate draws its `PdfSelection.geometry` using the same `paper.pageScale` as its `PdfPageImage`.
- Invariant: the cursor is an I-beam over a PDF page and an arrow in page gaps or surrounding workspace; native selection still decides whether text exists at the drag coordinates.

- [ ] **Step 1: Write failing production-QML contract tests**

Load `PdfReaderView.qml` through `QQuickWidget` and assert exact root properties/methods. With a generated three-line PDF, simulate a mouse drag on the QQuickWidget and assert `selectionFinalized` fires once after release, `selectedText` contains all three lines, and `grabFramebuffer()` contains blue pixels in all three rows. Repeat after setting zoom to `0.5`, `1.5`, and `3.0`. Move over the paper and page gap to assert I-beam and arrow cursor states.

- [ ] **Step 2: Run RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py -q
```

Expected: production QML files are missing.

- [ ] **Step 3: Create the controlled Qt 6.10.1 QML derivative**

Use the installed `PySide6/qml/QtQuick/Pdf/PdfMultiPageView.qml` as the complete reference. Copy its source into `LinguaPdfMultiPageView.qml` with the upstream copyright/SPDX header intact, then make only these changes:

```qml
signal selectionFinalized(int page, string text,
                          real fromX, real fromY, real toX, real toY,
                          var paths)
signal selectionReset()

function pointPaths(paths) {
    const result = []
    for (const path of paths) {
        const converted = []
        for (const point of path)
            converted.push({"x": point.x, "y": point.y})
        result.push(converted)
    }
    return result
}
```

On the delegate's selection drag transition from active to inactive, emit page, QML text, the numeric fields `selection.from.x / renderScale`, `selection.from.y / renderScale`, `selection.to.x / renderScale`, `selection.to.y / renderScale`, and `pointPaths(selection.geometry)`. Add a page-scoped `HoverHandler` with `cursorShape: Qt.IBeamCursor`; page gaps retain the root arrow cursor. Preserve the official `PdfPageImage`, `TableView`, `PdfSelection`, `PathMultiline`, page navigation, link delegates, and asynchronous rendering behavior.

- [ ] **Step 4: Add the stable wrapper root**

`PdfReaderView.qml` owns `PdfDocument`, exposes a session-only `password` property, and owns `LinguaPdfMultiPageView`. It forwards the signals, clamps zoom to `0.5...3.0`, and maps load errors:

```qml
function setZoomFactor(value) {
    viewer.renderScale = Math.max(0.5, Math.min(3.0, value))
}
function adjustZoom(steps) {
    setZoomFactor(viewer.renderScale + steps * 0.1)
}
function fitToWidth() {
    viewer.scaleToWidth(width, height)
    setZoomFactor(viewer.renderScale)
}
```

The wrapper, not Python, owns the `PdfDocument.source` binding.

- [ ] **Step 5: Run GREEN and inspect QML warnings**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py -q -s
```

Expected: tests pass with no `QQmlApplicationEngine failed`, missing module, binding-loop, or shader warnings.

- [ ] **Step 6: Commit**

```powershell
git add learning_assistant/ui/qml/LinguaPdfMultiPageView.qml learning_assistant/ui/qml/PdfReaderView.qml tests_v2/test_quick_pdf_view.py
git commit -m "feat: add native Qt Quick PDF viewer"
```

### Task 4: Add the QWidget adapter and switch PDF tabs

**Files:**
- Create: `learning_assistant/ui/quick_pdf_view.py`
- Modify: `learning_assistant/ui/pdf_reader_tab.py`
- Modify: `tests_v2/test_quick_pdf_view.py`
- Modify: `tests_v2/test_pdf_reader_ui.py`
- Modify: `tests_v2/test_pdf_tabs.py`

**Interfaces:**
- Produces: `QuickPdfViewAdapter(QWidget)` with the same public signals and methods consumed by `PdfReaderTab`.
- Signals: `selection_changed(object)`, `selection_feedback(str)`, `document_loaded(str, int)`, `load_failed(str)`, `current_page_changed(int)`, and `zoomFactorChanged(float)`.
- Methods: `load_file`, `set_pdf_password`, `close_document`, `current_selection`, `set_annotations`, `set_reading_theme`, `zoomFactor`, `set_zoom_factor`, `adjust_zoom`, `fit_to_width`, and `document`.
- Property: `document_key: str`.
- Invariant: one adapter owns one `QQuickWidget`, one indexing `QPdfDocument`, one `PdfViewBridge`, and one final selection.

- [ ] **Step 1: Write failing adapter contract tests**

Add a parameterized test covering load, password retry, selection signal, zoom clamp, fit width, close, and invalid file behavior:

```python
view = QuickPdfViewAdapter()
qtbot.addWidget(view)
view.resize(900, 700)
view.show()
assert view.load_file(pdf_path)
assert view.document().pageCount() == 1
assert view.document_key
view.set_zoom_factor(4.0)
assert view.zoomFactor() == 3.0
view.adjust_zoom(-1)
assert view.zoomFactor() == 2.9
view.close_document()
assert view.document().pageCount() == 0
```

Connect `QSignalSpy` to all public signals and assert the QML `selectionFinalized` signal flows through `PdfViewBridge` to `selection_changed` exactly once. Load a generated image-only PDF, release an empty selection, and assert `selection_feedback` emits `当前页面没有可选择文字，扫描版 PDF 暂不支持 OCR` without closing the document.

- [ ] **Step 2: Run RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_tabs.py -q
```

Expected: adapter import fails and the tab still creates `SelectablePdfView`.

- [ ] **Step 3: Implement adapter construction and QML error reporting**

Create a zero-margin layout containing `QQuickWidget` and set `SizeRootObjectToView`. Resolve QML relative to `Path(__file__).with_name("qml")`, which works from source and PyInstaller extraction. After the root reaches Ready, connect `selectionFinalized` to `PdfViewBridge.commit_selection`; no controller or repository is exposed as a QML context property. If `status() == QQuickWidget.Error`, join `widget.errors()` and emit `load_failed("PDF 阅读组件加载失败")` while logging the QML details.

- [ ] **Step 4: Implement document lifecycle and signals**

`load_file()` must load the indexing `QPdfDocument` first, derive `document_key`, reset selection, set root `documentSource` to `QUrl.fromLocalFile`, then emit `document_loaded(key, pageCount)`. Incorrect-password errors retain the candidate path and emit `此 PDF 需要密码`. `set_pdf_password()` sets the password on both the indexing document and QML root, retries that retained path, and never persists the password. `close_document()` clears root source and password before closing the indexing document. Connect root selection/page/zoom signals after QML reaches Ready; forward bridge selections to `_selection` and `selection_changed`. On `selectionReset`, query `getAllText(current_page)` only once for that release; emit the OCR feedback when the page has no text and otherwise clear the selection silently.

- [ ] **Step 5: Switch `PdfReaderTab` without leaking concrete QPdfView APIs**

Replace:

```python
from learning_assistant.ui.pdf_view import READING_THEMES, SelectablePdfView
```

with:

```python
from learning_assistant.ui.pdf_themes import READING_THEMES
from learning_assistant.ui.quick_pdf_view import QuickPdfViewAdapter
```

Construct `QuickPdfViewAdapter`, and connect `selection_feedback` to the tab status label. Update `test_pdf_tab_adjusts_zoom_and_fits_width` to assert the observable zoom percentage and adapter state, not `QPdfView.ZoomMode`.

- [ ] **Step 6: Run GREEN with multi-tab and shortcut regressions**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_tabs.py tests_v2/test_mode_router.py -q
```

- [ ] **Step 7: Commit exact files only**

```powershell
git add learning_assistant/ui/quick_pdf_view.py learning_assistant/ui/pdf_reader_tab.py tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_tabs.py
git commit -m "refactor: embed native PDF viewer in reading tabs"
```

### Task 5: Put themes and persistent annotations in the QML scene

**Files:**
- Create: `learning_assistant/ui/qml/shaders/page_tint.frag`
- Create: `learning_assistant/ui/qml/shaders/page_tint.frag.qsb`
- Modify: `learning_assistant/ui/qml/LinguaPdfMultiPageView.qml`
- Modify: `learning_assistant/ui/qml/PdfReaderView.qml`
- Modify: `learning_assistant/ui/quick_pdf_view.py`
- Modify: `learning_assistant/ui/pdf_reader_tab.py`
- Modify: `learning_assistant/pdf_controller.py`
- Modify: `tests_v2/test_quick_pdf_view.py`
- Modify: `tests_v2/test_pdf_reader_ui.py`
- Modify: `tests_v2/test_pdf_translation.py`

**Interfaces:**
- Python sets `themeId`, `themeColor`, and `annotationsByPage` on the QML root.
- `annotationsByPage` shape: `{pageIndexString: [{color: "#AARRGGBB", bounds: [[x, y, w, h], ...]}]}`.
- `PdfTranslationController.add_highlight(color)` emits `translation_failed("当前选区无法稳定标记，但仍可翻译")` and writes nothing when `selection.can_annotate` is false.
- Invariant: page multiply tint is below annotations and active selection; active selection remains the top highlight layer.

- [ ] **Step 1: Write failing theme, annotation, and safe-index tests**

Add framebuffer assertions for the exact eye-care paper color within tolerance, blue selection above the tint, and one yellow annotation before and after zoom. Add a controller test:

```python
controller.set_selection(
    PdfTextSelection(0, -1, -1, "translatable", ((10, 20, 80, 10),), False),
    "document-key",
)
controller.add_highlight("yellow")
assert repository.pdf_annotations("document-key") == []
assert failures == ["当前选区无法稳定标记，但仍可翻译"]
```

The tab test must leave Translate enabled while disabling Mark and Remove Mark for `can_annotate=False`.

- [ ] **Step 2: Run RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_translation.py -q
```

- [ ] **Step 3: Add and compile the multiply shader**

Create this Qt 6 fragment source:

```glsl
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 tint;
};
layout(binding = 1) uniform sampler2D source;
void main() {
    vec4 pixel = texture(source, qt_TexCoord0);
    fragColor = vec4(pixel.rgb * tint.rgb, pixel.a) * qt_Opacity;
}
```

Compile it with the bundled tool:

```powershell
..\..\.venv\Scripts\pyside6-qsb.exe --glsl "100 es,120,150" --hlsl 50 --msl 12 -o learning_assistant/ui/qml/shaders/page_tint.frag.qsb learning_assistant/ui/qml/shaders/page_tint.frag
```

- [ ] **Step 4: Render tint, annotations, and selection in one scene**

Wrap each `PdfPageImage` with `ShaderEffectSource` and the compiled `ShaderEffect` when `themeId != "white"`. Build three annotation `ShapePath` groups from `annotationsByPage` using `PathMultiline`, one per supported color. The z-order must be page image, tint result, persistent annotations, then active selection.

- [ ] **Step 5: Serialize annotations in the adapter**

`set_annotations()` groups repository objects by page and maps each bound without viewport conversion:

```python
payload.setdefault(str(annotation.page_index), []).append({
    "color": HIGHLIGHT_COLORS[annotation.color],
    "bounds": [list(bound) for bound in annotation.bounds],
})
root.setProperty("annotationsByPage", payload)
```

`set_reading_theme()` normalizes unknown IDs to `eye_care`, then sets `themeId` and `themeColor`.

- [ ] **Step 6: Enforce annotation eligibility at controller and UI boundaries**

Guard `PdfTranslationController.add_highlight`. In `PdfReaderTab._selection_changed`, enable Translate for every valid selection but enable mark controls only when `selection.can_annotate`. Show the non-blocking status `已选择 · 可翻译，当前版式暂不支持标记` for the fallback case.

- [ ] **Step 7: Run GREEN**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_translation.py tests_v2/test_pdf_repository.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add learning_assistant/ui/qml/shaders/page_tint.frag learning_assistant/ui/qml/shaders/page_tint.frag.qsb learning_assistant/ui/qml/LinguaPdfMultiPageView.qml learning_assistant/ui/qml/PdfReaderView.qml learning_assistant/ui/quick_pdf_view.py learning_assistant/ui/pdf_reader_tab.py learning_assistant/pdf_controller.py tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_translation.py
git commit -m "feat: render PDF themes and annotations natively"
```

### Task 6: Remove the legacy coordinate stack and update distribution metadata

**Files:**
- Delete: `learning_assistant/ui/pdf_view.py`
- Delete: `tests_v2/test_pdf_view.py`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `build.bat`

**Interfaces:**
- No runtime imports of `SelectablePdfView`, `PdfPageLayout`, `_visual_line_groups`, `_merge_selection_bounds`, or `QPdfView` remain.
- Future PyInstaller analysis imports `PySide6.QtQml`, `PySide6.QtQuick`, and `PySide6.QtQuickWidgets`, and includes project QML/shader resources.
- Invariant: this task updates build metadata but does not execute a build.

- [ ] **Step 1: Prove the legacy implementation is unused**

Run:

```powershell
rg -n "SelectablePdfView|PdfPageLayout|_visual_line_groups|_merge_selection_bounds|QtPdfWidgets|QPdfView" learning_assistant tests_v2
```

Expected: matches exist only in the two legacy files and documentation that this task updates. If production imports remain, move them to `QuickPdfViewAdapter` before deletion.

- [ ] **Step 2: Delete the superseded files**

Delete `learning_assistant/ui/pdf_view.py` and `tests_v2/test_pdf_view.py`. This intentionally removes the uncommitted manual-overlay experiment as well as the original hand-built coordinate stack.

- [ ] **Step 3: Update architecture and user documentation**

In `docs/ARCHITECTURE.md`, replace the manual page-bounds description with:

```text
PdfReaderTab -> QuickPdfViewAdapter -> QQuickWidget/PdfSelection
             -> PdfViewBridge -> PdfTextSelection -> PdfTranslationController
```

State that QML owns page pixels and visual selection while Python owns translation, persistence, privacy, and shortcuts. In `README.md`, retain the same user controls and note that complex formulas and mixed fonts now use native selection geometry.

- [ ] **Step 4: Record Qt-derived source licensing**

Add a Qt section to `THIRD_PARTY_NOTICES.md` naming `LinguaPdfMultiPageView.qml`, Qt 6.10.1, The Qt Company Ltd., and the retained LGPL-3.0-only/GPL license header. Do not relabel the derived file as project-only code.

- [ ] **Step 5: Update future build inputs without packaging**

Add these PyInstaller arguments in `build.bat`:

```bat
    --add-data "learning_assistant\ui\qml;learning_assistant\ui\qml" ^
    --hidden-import PySide6.QtQml ^
    --hidden-import PySide6.QtQuick ^
    --hidden-import PySide6.QtQuickWidgets ^
```

The QtQml PyInstaller hook collects Qt's QML import tree; the explicit data argument collects only project-owned QML and the compiled shader.

- [ ] **Step 6: Run focused regressions after deletion**

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_quick_pdf_view.py tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_tabs.py tests_v2/test_mode_router.py -q
rg -n "SelectablePdfView|PdfPageLayout|QtPdfWidgets|QPdfView" learning_assistant tests_v2
```

Expected: tests pass and `rg` returns no matches.

- [ ] **Step 7: Commit exact removal and metadata files**

```powershell
git add learning_assistant/ui/pdf_view.py tests_v2/test_pdf_view.py README.md docs/ARCHITECTURE.md THIRD_PARTY_NOTICES.md build.bat
git commit -m "refactor: retire manual PDF selection geometry"
```

### Task 7: Full verification and source acceptance handoff

**Files:**
- Modify only if verification exposes a scoped defect in files from Tasks 1–6.

**Interfaces:**
- Acceptance evidence includes automated results, real-PDF screenshots, selection latency, worktree status, and an exact source run command.
- Invariant: do not package or push at the end of this task.

- [ ] **Step 1: Run fresh complete automated verification**

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m compileall -q learning_assistant tools
git diff --check
```

Expected: zero failures, compilation exit 0, and no whitespace errors.

- [ ] **Step 2: Verify QML resources and license headers**

```powershell
rg -n "SPDX-License-Identifier|Copyright \(C\).*The Qt Company" learning_assistant/ui/qml/LinguaPdfMultiPageView.qml
Test-Path learning_assistant/ui/qml/shaders/page_tint.frag.qsb
git ls-files learning_assistant/ui/qml
```

Expected: the copied QML retains both lines, the QSB exists, and all intended QML resources are tracked.

- [ ] **Step 3: Run the exact real-PDF acceptance matrix in the production app**

Start source code with:

```powershell
..\..\.venv\Scripts\python.exe main.py
```

Open the problem paper in PDF mode at the active Windows display scale. Verify the `Cloth subspace` paragraph, formula-heavy paragraph, and double-column boundary at 50%, 100%, 150%, 200%, and 300%. Then run the production adapter smoke test in a fresh process with `QT_SCALE_FACTOR=1.0`, `1.25`, and `1.5`; at each scale, capture the same deterministic page/selection framebuffer and compare its normalized selection bounds with the `PdfSelection.geometry` bounds. Do not treat `renderScale` as a substitute for Windows logical-DPI coverage. Confirm scrolling and tab switching do not move active selection or saved annotations.

- [ ] **Step 4: Measure the view boundary latency**

Use `QElapsedTimer` instrumentation around QML `selectionFinalized` and Python `selection_changed` in the smoke tool, collect at least 20 releases, and report median and maximum. Both must remain under 30 ms locally. Remove temporary timing logs from production files before committing any correction.

- [ ] **Step 5: Inspect the complete branch and repository hygiene**

```powershell
git status --short
git diff v1..HEAD --check
git diff --name-only 73dbc98..HEAD -- "*.pdf" "*.png" "*.log"
git ls-files "*.qsb"
rg -n "C:\\Users\\|三枪|neural cloth simulation" learning_assistant tests_v2 tools docs README.md build.bat
```

Expected: this implementation adds no problem PDFs, screenshots, logs, caches, build artifacts, secrets, or unrelated files; the only intended binary asset added by this plan is `page_tint.frag.qsb`.

- [ ] **Step 6: Stop for user source acceptance**

Report exact test counts, latency results, visual cases, changed architecture, and remaining limitations for scanned or malformed-text PDFs. Provide the source run command. Do not run `build.bat`, create a release, or push GitHub until the user explicitly accepts the source implementation.
