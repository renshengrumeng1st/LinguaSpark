# PDF Multi-Tab, Selection, and Focus Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn PDF reading into a maximized multi-document workspace with independent tab sessions, reliable live text selection, contextual shortcuts, and an Esc-exitable focus mode.

**Architecture:** Split the current single-window implementation into a global `PdfReaderWindow` container and one self-contained `PdfReaderTab` per document. Each tab owns its view, translation controller, and result widgets, while all controllers share one concurrent `QtPdfTranslationClient`, settings store, and repository; selection hit-testing remains local to `SelectablePdfView`.

**Tech Stack:** Python 3.14, PySide6 Essentials/Addons 6.10.1, QtPdf/QtPdfWidgets, SQLite, pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-08-19-pdf-tabs-focus-selection-design.md`

## Global Constraints

- Work only on local branch `feature/pdf-reader`; do not push.
- Do not build a PyInstaller artifact before user acceptance.
- Application cold start still shows the mode chooser; `Alt+Q` directly shows compact mode.
- PDF mode opens maximized; focus mode hides the toolbar and tab bar, and `Esc` restores maximized mode.
- Only the active tab participates in `Alt+W`; without an active PDF selection, fall back to system selection translation.
- Each PDF tab independently preserves document, scroll, zoom, selection, translation, phrases, annotations, and request state.
- All tabs share one `QtPdfTranslationClient`; closing one tab cancels only its active request.
- Selection remains limited to one page; OCR and cross-page selection remain out of scope.
- The primary model decides delegation under `AGENTS.md`; this plan is suitable for inline execution.

## File Structure

- `learning_assistant/ui/pdf_view.py`: lazy page text bounds, I-beam hover, endpoint snapping, live selection preview, and final selection emission.
- `learning_assistant/pdf_controller.py`: shared-client lifecycle and explicit per-session disposal.
- `learning_assistant/ui/pdf_reader_tab.py`: one complete PDF document session, including the split PDF/translation UI and per-tab controller wiring.
- `learning_assistant/ui/pdf_reader_window.py`: global toolbar, tab container, duplicate detection, empty state, active-tab proxy methods, maximized display, and focus mode.
- `learning_assistant/application.py`: shared PDF client composition, `Alt+Q` compact routing, active-tab `Alt+W`, and application shutdown.
- `tests_v2/test_pdf_view.py`: real-PDF selection snapping, cursor, live preview, and high-DPI regressions.
- `tests_v2/test_pdf_translation.py`: two controllers sharing one client and independent cancellation.
- `tests_v2/test_pdf_reader_ui.py`: tab session UI and translation behavior.
- `tests_v2/test_pdf_tabs.py`: real multi-document window, duplicates, state isolation, closing, focus mode, and maximized display.
- `tests_v2/test_mode_router.py`: compact shortcut and active-tab PDF shortcut routing.

---

### Task 1: Reliable hover and live PDF text selection

**Files:**
- Modify: `learning_assistant/ui/pdf_view.py`
- Test: `tests_v2/test_pdf_view.py`

**Interfaces:**
- Produces: `SelectablePdfView.has_selectable_text_near(position: QPointF) -> bool`.
- Produces: `SelectablePdfView._selection_for_drag(start, end) -> PdfTextSelection | None` as an internal single selection path used by move and release events.
- Invariant: mouse movement may update `current_selection()` for preview, but `selection_changed` emits only once on release.
- Invariant: page text bounds are cached lazily and cleared whenever a document is loaded or closed.

- [ ] **Step 1: Add failing real-PDF snapping, cursor, and preview tests**

Add tests using `_write_two_page_pdf` and a visible `SelectablePdfView`:

```python
def test_drag_from_near_line_snaps_to_pdf_text(qtbot, tmp_path):
    path = tmp_path / "snap.pdf"
    _write_two_page_pdf(path)
    view = SelectablePdfView()
    qtbot.addWidget(view)
    view.resize(1000, 500)
    view.show()
    assert view.load_file(path)
    layout = view._layout()
    start = layout.pdf_rect_to_viewport(0, (66, 52, 1, 1), 0).center().toPoint()
    end = layout.pdf_rect_to_viewport(0, (245, 86, 1, 1), 0).center().toPoint()
    qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=end)
    assert view.current_selection() is not None
    assert "First page sentence." in view.current_selection().text
    qtbot.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
```

Add a `QSignalSpy` assertion that `selection_changed` has length `0` during the move and length `1` after release. Move without buttons to a point 5 PDF points outside the line and assert `view.viewport().cursor().shape() == Qt.IBeamCursor`; move far from text and assert `Qt.ArrowCursor`. Add a far-away drag test that leaves `current_selection()` as `None`.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view.py -q
```

Expected: near-line drag has no preview, cursor remains an arrow, and selection is emitted only by the existing raw-coordinate release path.

- [ ] **Step 3: Implement cached text hit bounds and endpoint snapping**

In `SelectablePdfView.__init__`, enable mouse tracking on the viewport and add:

```python
self.viewport().setMouseTracking(True)
self._page_text_bounds: dict[int, tuple[QRectF, ...]] = {}
```

Clear the cache in `load_file`. Add `_text_bounds(page_index)` that converts `self._document.getAllText(page_index).bounds()` polygons to non-empty `QRectF` values and caches them. Add `_nearest_text_point(page_index, point, max_distance=10.0)` that returns the original point inside a bound or the closest clamped point when Euclidean distance to a bound is at most 10 PDF points; inset a clamped edge by 0.5 point so Qt receives a point inside the glyph region.

Add `_selection_for_drag(start, end)` that first calls `getSelection` with raw points, then retries with snapped points when invalid, normalizes text, converts polygons to bounds, orders indices, and returns `PdfTextSelection`. It must return `None` instead of emitting signals or messages.

- [ ] **Step 4: Update mouse interaction without business churn**

On hover, call `_hit`, query `_nearest_text_point`, and set the viewport cursor to `Qt.IBeamCursor` only near text. On left press, start a drag only when the press point can snap to text. On drag move, compute `_selection_for_drag`, assign it to `_selection`, repaint immediately, and do not emit `selection_changed`. On release, compute once more, repaint, and emit exactly one final selection or `None`.

- [ ] **Step 5: Run GREEN and mutation checks**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view.py -q
```

Mentally verify the tests fail if the 10-point limit is removed, cache clearing is omitted, preview emission happens on every move, snapping is removed, or the cursor never resets.

- [ ] **Step 6: Commit**

```powershell
git add learning_assistant/ui/pdf_view.py tests_v2/test_pdf_view.py
git commit -m "fix: make PDF text selection responsive"
```

### Task 2: Shared translation client and per-tab controller lifecycle

**Files:**
- Modify: `learning_assistant/pdf_controller.py`
- Test: `tests_v2/test_pdf_translation.py`

**Interfaces:**
- Produces: `PdfTranslationController.dispose() -> None` that cancels only its active request, disconnects shared-client signals, and makes later client emissions inert.
- Produces: `PdfTranslationController.active_request_id -> int | None` read-only property for lifecycle diagnostics.
- Consumes: one shared `QtPdfTranslationClient` whose request IDs are globally unique and whose requests can run concurrently.

- [ ] **Step 1: Write failing shared-client isolation tests**

Create two real `PdfTranslationController` instances using the existing signal-compatible fake client, separate selections, and the same settings/repository:

```python
first.translate_selection()
second.translate_selection()
first_id, second_id = fake.started_ids
fake.translation_partial.emit(second_id, "第二个标签")
assert first_partials == []
assert second_partials == ["第二个标签"]
first.dispose()
fake.translation_partial.emit(first_id, "迟到结果")
assert first_partials == []
assert fake.cancelled_ids == [first_id]
```

Also assert disposing the first controller does not cancel `second_id`, and disposing twice is harmless.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_translation.py -q
```

Expected: FAIL because `dispose` and `active_request_id` do not exist.

- [ ] **Step 3: Implement explicit lifecycle**

Add `_disposed = False`, expose the active request ID property, and make all client signal handlers return immediately after disposal. `dispose` calls `cancel()`, disconnects `_on_partial`, `_on_phrase`, `_on_completed`, and `_on_failed` from the client with `RuntimeError`/`TypeError` tolerance, then marks the controller disposed. `translate_selection`, selection changes, and annotation mutations become no-ops after disposal.

- [ ] **Step 4: Run GREEN and existing client regressions**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_translation.py tests_v2/test_ai_client.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/pdf_controller.py tests_v2/test_pdf_translation.py
git commit -m "feat: isolate PDF translation sessions"
```

### Task 3: Extract one independent PDF reader tab

**Files:**
- Create: `learning_assistant/ui/pdf_reader_tab.py`
- Modify: `learning_assistant/ui/pdf_reader_window.py`
- Modify: `tests_v2/test_pdf_reader_ui.py`

**Interfaces:**
- Produces: `PdfReaderTab(controller: PdfTranslationController, settings: SettingsStore, parent=None)`.
- Produces: `load_file(path: str | Path) -> bool`, `path: Path | None`, `document_key: str`, `has_active_selection() -> bool`, `translate_active_selection() -> None`, `set_reading_theme(theme_id: str) -> None`, and `close_session() -> None`.
- Produces signals: `status_changed(str)` and `zoom_changed(float)`.
- Invariant: the tab owns the existing splitter, PDF view, source/translation/phrase widgets, highlight actions, and all per-document signal wiring.

- [ ] **Step 1: Move existing single-session UI tests to a wished-for tab API**

Update `tests_v2/test_pdf_reader_ui.py` to construct `PdfReaderTab(FakePdfController(), settings)`. Keep the existing assertions for eye-care theme, hidden phrase panel, streamed translation before phrases, cached completion, selection actions, copy, zoom, and splitter ratio. Add:

```python
def test_close_session_cancels_controller_and_closes_document(...):
    tab = PdfReaderTab(controller, settings)
    assert tab.load_file(pdf_path)
    tab.close_session()
    assert controller.dispose_calls == 1
    assert tab.pdf_view.document().pageCount() == 0
```

Extend `FakePdfController` with a `dispose_calls` counter and `dispose()`.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_reader_ui.py -q
```

Expected: collection fails because `learning_assistant.ui.pdf_reader_tab` does not exist.

- [ ] **Step 3: Extract `PdfReaderTab` without changing behavior**

Move the current splitter, `SelectablePdfView`, translation panel, phrase panel, selection actions, controller connections, and translation rendering methods from `PdfReaderWindow` into `PdfReaderTab(QWidget)`. Keep widget attribute names stable for the existing tests. `load_file` stores the resolved path only after a successful view load, initializes controller document identity and annotations, and emits status changes. `close_session` is idempotent, calls `controller.dispose()`, closes the document, and clears the stored path.

Leave `PdfReaderWindow` temporarily as a thin single-tab wrapper so imports continue to work until Task 4; it may construct one `PdfReaderTab` and proxy the existing public methods.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_reader_ui.py tests_v2/test_pdf_view.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/ui/pdf_reader_tab.py learning_assistant/ui/pdf_reader_window.py tests_v2/test_pdf_reader_ui.py
git commit -m "refactor: extract PDF reader tab session"
```

### Task 4: Multi-document tab container

**Files:**
- Modify: `learning_assistant/ui/pdf_reader_window.py`
- Create: `tests_v2/test_pdf_tabs.py`

**Interfaces:**
- `PdfReaderWindow(settings, controller_factory, parent=None)` consumes `controller_factory() -> PdfTranslationController`.
- Produces: `active_tab() -> PdfReaderTab | None`, `open_file(path=None) -> bool`, `close_tab(index: int) -> None`, `close_all_tabs() -> None`, `has_active_selection() -> bool`, and `translate_active_selection() -> None`.
- Produces: `tab_widget: QTabWidget`, `content_stack: QStackedWidget`, and `empty_page: QWidget` for stable UI tests.
- Invariant: canonical resolved case-folded paths are unique across tabs.

- [ ] **Step 1: Write failing real multi-document tests**

Generate two PDFs with different filenames and assert:

```python
window = PdfReaderWindow(settings, lambda: FakePdfController())
assert window.open_file(first)
assert window.open_file(second)
assert window.tab_widget.count() == 2
first_tab = window.tab_widget.widget(0)
second_tab = window.tab_widget.widget(1)
first_tab.pdf_view.set_zoom_factor(1.5)
second_tab.pdf_view.set_zoom_factor(0.8)
window.tab_widget.setCurrentIndex(0)
assert window.active_tab().pdf_view.zoomFactor() == pytest.approx(1.5)
window.tab_widget.setCurrentIndex(1)
assert window.active_tab().pdf_view.zoomFactor() == pytest.approx(0.8)
```

Add tests that a duplicate resolved path keeps count `2` and selects its existing index, tab titles equal filenames, tooltips equal resolved paths, closing one tab invokes only its controller disposal, and closing the last tab selects `empty_page`.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_tabs.py -q
```

Expected: FAIL because the window still exposes a single session and old constructor.

- [ ] **Step 3: Implement the global toolbar, tab widget, and empty state**

Build a stored `toolbar_widget` containing Open, Compact, Focus, zoom, fit-width, theme, and Settings controls. Place a closable `QTabWidget` and an empty-state page in `content_stack`. Keep the translation action controls inside each `PdfReaderTab`.

`open_file` resolves the path, checks an internal `dict[str, PdfReaderTab]` keyed by `str(path).casefold()`, and selects duplicates. For a new path, create a controller from `controller_factory`, create a `PdfReaderTab`, call `load_file`, and add it only on success. Store the full path as tooltip, update `last_directory`, select the tab, and switch the stack to tabs.

- [ ] **Step 4: Route global controls to the active tab**

Zoom out/in, fit width, and the zoom label read the active tab. On tab changes, disconnect the old tab's `zoom_changed`, connect the new one, update percentage, and keep the global theme applied to every tab. Disable zoom and focus controls when no tab exists. `has_active_selection` and `translate_active_selection` delegate only to `active_tab()`.

- [ ] **Step 5: Implement deterministic close behavior**

`close_tab` obtains the widget, removes it from the path map and tab widget, calls `close_session`, and schedules deletion. Select the adjacent tab automatically; after the last close, switch to `empty_page`. `close_all_tabs` closes from the last index down so shutdown cannot skip shifted indices.

- [ ] **Step 6: Run GREEN with UI regressions**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_tabs.py tests_v2/test_pdf_reader_ui.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add learning_assistant/ui/pdf_reader_window.py tests_v2/test_pdf_tabs.py
git commit -m "feat: open multiple PDF reading tabs"
```

### Task 5: Maximized PDF mode and focus reading

**Files:**
- Modify: `learning_assistant/ui/pdf_reader_window.py`
- Modify: `tests_v2/test_pdf_tabs.py`

**Interfaces:**
- Produces: `enter_focus_mode() -> None`, `exit_focus_mode() -> None`, and `is_focus_mode() -> bool`.
- Invariant: focus mode never recreates or clears a tab; it only changes visibility and window state.
- Invariant: `Esc` exits focus only when focus is active.

- [ ] **Step 1: Write failing maximized and focus-mode tests**

Use pytest-qt with one loaded PDF:

```python
window.show_front()
assert window.isMaximized()
window.enter_focus_mode()
assert window.isFullScreen()
assert window.toolbar_widget.isHidden()
assert window.tab_widget.tabBar().isHidden()
active = window.active_tab()
qtbot.keyClick(window, Qt.Key_Escape)
assert window.isMaximized()
assert not window.toolbar_widget.isHidden()
assert not window.tab_widget.tabBar().isHidden()
assert window.active_tab() is active
```

Also assert the focus button is disabled with no tabs and ordinary `Esc` does not hide or resize a non-focus window.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_tabs.py -q
```

Expected: focus methods are missing and `show_front` calls `showNormal`.

- [ ] **Step 3: Implement maximized and focus states**

Change `show_front` to `showMaximized`, then raise and activate. Add `_focus_mode = False`. `enter_focus_mode` returns with no active tab; otherwise it hides `toolbar_widget` and `tab_widget.tabBar()`, calls `showFullScreen`, and leaves `content_stack` untouched. `exit_focus_mode` reverses visibility, calls `showMaximized`, and restores focus to the active PDF view.

Override `keyPressEvent`; consume `Qt.Key_Escape` only while `_focus_mode`, otherwise call the superclass. Ensure `closeEvent` exits focus state before hiding so the next display is maximized and not missing controls.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_tabs.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/ui/pdf_reader_window.py tests_v2/test_pdf_tabs.py
git commit -m "feat: add focused PDF reading mode"
```

### Task 6: Application composition and contextual shortcuts

**Files:**
- Modify: `learning_assistant/application.py`
- Modify: `tests_v2/test_mode_router.py`

**Interfaces:**
- Application owns one `QtPdfTranslationClient` created lazily with the PDF window.
- `PdfReaderWindow` receives a controller factory that constructs `PdfTranslationController(settings, repository, shared_client)` per tab.
- `LearningAssistantApplication._hotkey("window")` delegates to `mode_router.show_compact()`.
- `LearningAssistantApplication.quit()` calls `pdf_window.close_all_tabs()` and `shared_client.cancel()` when created.

- [ ] **Step 1: Update failing routing and composition tests**

Change the current window-hotkey expectation from chooser to compact:

```python
def test_window_hotkey_opens_compact_mode():
    calls = []
    application = LearningAssistantApplication.__new__(LearningAssistantApplication)
    application.mode_router = SimpleNamespace(
        pdf_window=None,
        show_compact=lambda: calls.append("compact"),
    )
    application._hotkey("window")
    assert calls == ["compact"]
```

Extend the PDF fake window to expose active-tab selection semantics and retain the existing assertions that `Alt+W` prefers a visible PDF selection and falls back otherwise. Add a construction test with fake settings/repository/client proving two calls to the controller factory share the same client object.

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_mode_router.py -q
```

Expected: the window shortcut still records `chooser` and the PDF factory still creates one controller eagerly.

- [ ] **Step 3: Refactor lazy PDF composition**

Replace `self.pdf_controller` with `self.pdf_client: QtPdfTranslationClient | None`. In `_create_pdf_window`, create the shared client once, define a zero-argument controller factory closing over settings/repository/client, and instantiate the new `PdfReaderWindow(settings, controller_factory)`. Keep compact/settings signal wiring.

Change `_hotkey("window")` to `self.mode_router.show_compact()`. Keep `_hotkey("selection")` delegating through `pdf_window.has_active_selection()`, which now means the active tab only.

- [ ] **Step 4: Refactor shutdown**

If a PDF window exists, call `close_all_tabs()`. If a shared client exists, call `cancel()` with no request ID. Remove the obsolete single-controller cancellation branch.

- [ ] **Step 5: Run GREEN and mode regressions**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_mode_router.py tests_v2/test_ui_smoke.py tests_v2/test_selection.py tests_v2/test_hotkey_settings.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add learning_assistant/application.py tests_v2/test_mode_router.py
git commit -m "feat: compose multi-tab PDF sessions"
```

### Task 7: Documentation and complete source verification

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Document multi-PDF tabs, independent tab state, improved selection, `Alt+Q`, maximized PDF mode, focus button, and `Esc`.
- Preserve the existing statement that only selected text and language settings reach the model.

- [ ] **Step 1: Update user and architecture documentation**

In `README.md`, describe opening multiple PDFs, closing/switching tabs, focus reading, and updated shortcuts. In `docs/ARCHITECTURE.md`, replace the single PDF workspace description with `PdfReaderWindow -> PdfReaderTab -> PdfTranslationController`, noting the shared concurrent client and per-tab request filtering.

- [ ] **Step 2: Run fresh full verification**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m compileall -q learning_assistant
```

Expected: all tests pass, compilation exits 0, and no warnings/errors are introduced.

- [ ] **Step 3: Run offscreen startup and real multi-document smoke checks**

With isolated `APPDATA` and `QT_QPA_PLATFORM=offscreen`, construct `LearningAssistantApplication`, show the chooser, and assert neither mode is created. Then show PDF mode, open two generated PDFs, set different zoom/scroll state, switch tabs, enter/exit focus with `Esc`, and assert each session is preserved. Quit without entering the event loop.

- [ ] **Step 4: Inspect the entire feature diff**

Run:

```powershell
git diff v1..HEAD --check
git status --short
git ls-files "*.pdf"
```

Confirm no secrets, generated PDFs, caches, build output, user-specific paths, or virtual-environment files are tracked.

- [ ] **Step 5: Commit documentation only**

```powershell
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: explain multi-PDF focus reading"
```

- [ ] **Step 6: Stop before packaging or pushing**

Leave the verified implementation on local `feature/pdf-reader`, provide the exact source run command and acceptance checklist, and do not run `build.bat` or push the branch.
