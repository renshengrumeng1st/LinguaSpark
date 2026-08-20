# PDF Reader Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuously scrolling PDF reading mode with fast streamed translation, phrase analysis, eye-care themes, and persistent highlights while preserving the current compact mode.

**Architecture:** Keep the existing application composition root and add lazy mode routing. PDF rendering/selection, translation orchestration, persistence, and widgets live behind separate interfaces; `Alt+W` routes to the active PDF selection only when one exists. Translation uses one streamed request whose translation appears before a delimiter-separated phrase section.

**Tech Stack:** Python 3.14, PySide6 Essentials/Addons 6.10.1, QtPdf/QtPdfWidgets, SQLite, pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-08-19-pdf-reader-mode-design.md`

## Global Constraints

- Work only on local branch `feature/pdf-reader`; do not push.
- Do not build a PyInstaller artifact before user acceptance.
- The left PDF pane must use continuous multi-page mouse-wheel scrolling.
- `Alt+W` must show translation progress within 50 ms of the local key event; model latency is measured separately.
- Translation and at most five phrase explanations share one model request; phrase generation must not delay translation rendering.
- Only the selected text may be sent to the configured model.
- Existing compact translation, system selection, learning, speech, and review behavior must remain compatible.
- The primary model decides whether delegation is useful according to `AGENTS.md`; this plan is suitable for inline execution.

## File Structure

- `learning_assistant/domain/pdf_models.py`: PDF selection, phrase, translation result, and annotation value objects.
- `learning_assistant/services/pdf_text.py`: text normalization, document identity, and streamed translation/phrase parser.
- `learning_assistant/services/pdf_translation.py`: dedicated Qt network client for the low-latency PDF protocol.
- `learning_assistant/pdf_controller.py`: selection state, cache, cancellation, request isolation, and annotation orchestration.
- `learning_assistant/storage/learning_repository.py`: PDF annotation schema and CRUD.
- `learning_assistant/ui/pdf_view.py`: continuous `QPdfView.MultiPage`, coordinate mapping, selection, theme tint, and highlight overlay.
- `learning_assistant/ui/pdf_reader_window.py`: PDF toolbar, split reading/translation layout, themes, and actions.
- `learning_assistant/ui/mode_chooser.py`: startup choice between compact and PDF modes.
- `learning_assistant/application.py`: lazy window composition, tray mode switching, and contextual `Alt+W` routing.
- `requirements.txt`: QtPdf/QtPdfWidgets dependency.
- `tests_v2/test_pdf_text.py`, `test_pdf_repository.py`, `test_pdf_translation.py`, `test_pdf_view.py`, `test_pdf_reader_ui.py`, `test_mode_router.py`: focused regressions.

---

### Task 1: PDF value objects and streaming protocol

**Files:**
- Create: `learning_assistant/domain/pdf_models.py`
- Create: `learning_assistant/services/pdf_text.py`
- Create: `tests_v2/test_pdf_text.py`

**Interfaces:**
- Produces: `PdfPhrase(source: str, meaning: str)`, `PdfTranslationResult(translation: str, phrases: tuple[PdfPhrase, ...])`, `PdfTextSelection(page_index, start_index, end_index, text, bounds)`.
- Produces: `normalize_pdf_selection(text: str, max_length: int = 4000) -> str`; empty input returns `""`, over-limit input raises `ValueError`.
- Produces: `document_key(path: Path) -> str` from resolved case-folded path, size, and `st_mtime_ns`.
- Produces: `PdfTranslationStreamParser.feed(chunk: str) -> PdfStreamUpdate` and `.close() -> PdfTranslationResult`.

- [ ] **Step 1: Write failing normalization and stream-parser tests**

```python
def test_normalize_pdf_selection_joins_hyphenated_line_breaks():
    assert normalize_pdf_selection("A trans-\nlation  test.\nNext") == "A translation test. Next"

def test_stream_parser_handles_delimiter_split_between_chunks():
    parser = PdfTranslationStreamParser()
    first = parser.feed("自然译文<<<PHRA")
    second = parser.feed("SES>>>\ntake part || 参加\nin context || 在语境中\n")
    result = parser.close()
    assert first.translation_delta == "自然译文"
    assert second.phrases == (
        PdfPhrase("take part", "参加"),
        PdfPhrase("in context", "在语境中"),
    )
    assert result.translation == "自然译文"

def test_stream_parser_without_delimiter_keeps_all_text_as_translation():
    parser = PdfTranslationStreamParser()
    parser.feed("只有译文")
    assert parser.close() == PdfTranslationResult("只有译文", ())
```

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_text.py -q`

Expected: FAIL because `pdf_models` and `pdf_text` do not exist.

- [ ] **Step 3: Implement minimal immutable models, normalization, identity, and parser**

The parser must withhold only the suffix that could be the beginning of `<<<PHRASES>>>`, emit translation deltas immediately, parse only complete `source || meaning` lines, strip duplicates, and cap phrases at five. `close()` flushes a missing-delimiter buffer into translation and ignores malformed phrase lines.

- [ ] **Step 4: Run GREEN and focused mutation checks**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_text.py -q`

Then temporarily reason through delimiter removal, a split at every delimiter character, six phrase lines, blank fields, and a 4,001-character selection; each realistic break must be caught by a test.

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/domain/pdf_models.py learning_assistant/services/pdf_text.py tests_v2/test_pdf_text.py
git commit -m "feat: add PDF text and stream protocol"
```

### Task 2: Persistent PDF annotations

**Files:**
- Modify: `learning_assistant/storage/learning_repository.py` (`_initialize` and new annotation methods)
- Test: `tests_v2/test_pdf_repository.py`

**Interfaces:**
- Consumes: `PdfTextSelection` and document key from Task 1.
- Produces: `add_pdf_annotation(document_key, selection, color, now=None) -> PdfAnnotation`.
- Produces: `pdf_annotations(document_key, page_index=None) -> list[PdfAnnotation]`.
- Produces: `delete_pdf_annotation(document_key, page_index, start_index, end_index) -> bool`.
- Invariant: colors are exactly `yellow`, `green`, or `pink`; duplicate document/page/range annotations update color instead of duplicating.

- [ ] **Step 1: Write failing real-SQLite CRUD tests**

```python
def test_pdf_annotation_round_trip_and_color_update(tmp_path):
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    selection = PdfTextSelection(2, 10, 24, "selected phrase", ((1.0, 2.0, 30.0, 8.0),))
    repo.add_pdf_annotation("doc", selection, "yellow", now=100)
    repo.add_pdf_annotation("doc", selection, "green", now=101)
    saved = repo.pdf_annotations("doc", page_index=2)
    assert len(saved) == 1
    assert saved[0].color == "green"
    assert repo.delete_pdf_annotation("doc", 2, 10, 24) is True
    assert repo.pdf_annotations("doc") == []
```

Also test invalid colors and isolation between document keys.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_repository.py -q`

Expected: FAIL because the schema and repository methods are missing.

- [ ] **Step 3: Add schema and parameterized CRUD**

Use a uniqueness constraint on `(document_key, page_index, start_index, end_index)`, JSON encode bounds, validate before SQL, and keep the existing WAL/short-transaction pattern.

- [ ] **Step 4: Run GREEN plus repository regression**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_repository.py tests_v2/test_learning_repository.py -q`

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/storage/learning_repository.py tests_v2/test_pdf_repository.py
git commit -m "feat: persist PDF highlights"
```

### Task 3: Fast streamed PDF translation and controller

**Files:**
- Create: `learning_assistant/services/pdf_translation.py`
- Create: `learning_assistant/pdf_controller.py`
- Create: `tests_v2/test_pdf_translation.py`

**Interfaces:**
- `QtPdfTranslationClient.start(profile, text, languages) -> int`; signals `translation_partial(int, str)`, `phrase_ready(int, object)`, `completed(int, object, object)`, `failed(int, str, object)`; `cancel(request_id=None)`.
- `PdfTranslationController.set_selection(selection, document_key)` stores only local state.
- `PdfTranslationController.translate_selection()` emits `translation_started`, serves cache synchronously, or starts one network request.
- `PdfTranslationController.add_highlight(color)` and `.delete_highlight()` delegate to repository and emit refreshed annotations.

- [ ] **Step 1: Write failing payload, cache, and stale-request tests**

Use a small signal-compatible fake only for the external network client; use real `SettingsStore` and `LearningRepository` in temporary files.

```python
def test_pdf_controller_ignores_late_result_from_cancelled_selection(...):
    controller.set_selection(first, "doc")
    controller.translate_selection()
    first_id = fake_client.started_ids[-1]
    controller.set_selection(second, "doc")
    controller.translate_selection()
    fake_client.translation_partial.emit(first_id, "旧译文")
    assert partial_spy == []

def test_pdf_controller_cache_hit_avoids_network(...):
    repository.put_ai_cache(expected_key, {
        "translation": "缓存译文",
        "phrases": [{"source": "take part", "meaning": "参加"}],
    })
    controller.translate_selection()
    assert fake_client.start_calls == []
    assert completed_spy[-1].translation == "缓存译文"
```

Test the request payload separately: translation comes first, includes `<<<PHRASES>>>`, requests at most five phrases, uses temperature `0.1` and `max_tokens` `768`, and sends no path/annotation data.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_translation.py -q`

Expected: FAIL because the client and controller do not exist.

- [ ] **Step 3: Implement the dedicated client and controller**

Reuse `SSEContentParser` from `services.ai_client`, but keep PDF request state separate. Feed content tokens through `PdfTranslationStreamParser`; emit translation deltas before phrase lines. Disable thinking for BigModel-compatible endpoints as the existing client does. Cache only completed results and record timings with query kind `pdf_selection`.

- [ ] **Step 4: Run GREEN and AI regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_translation.py tests_v2/test_ai_client.py -q`

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/services/pdf_translation.py learning_assistant/pdf_controller.py tests_v2/test_pdf_translation.py
git commit -m "feat: stream PDF translations and phrase analysis"
```

### Task 4: Continuous PDF view and text selection

**Files:**
- Modify: `requirements.txt`
- Create: `learning_assistant/ui/pdf_view.py`
- Create: `tests_v2/test_pdf_view.py`

**Interfaces:**
- Add dependency `PySide6-Addons==6.10.1`.
- `PdfPageLayout(page_sizes, zoom, viewport_width, margins, spacing)` maps viewport/content points to `(page_index, QPointF)` and PDF bounds back to viewport rectangles.
- `SelectablePdfView.load_file(path)`, `current_selection()`, `set_annotations(items)`, `set_reading_theme(theme_id)`, `set_zoom_factor(value)`.
- Signals: `selection_changed(object)`, `document_loaded(str, int)`, `load_failed(str)`, `current_page_changed(int)`.

- [ ] **Step 1: Install the approved Qt module**

Run: `..\..\.venv\Scripts\python.exe -m pip install PySide6-Addons==6.10.1`

Verify: `..\..\.venv\Scripts\python.exe -c "from PySide6.QtPdf import QPdfDocument; from PySide6.QtPdfWidgets import QPdfView; print('QtPdf ready')"`

- [ ] **Step 2: Write failing geometry and integration tests**

```python
def test_page_layout_accounts_for_scroll_and_different_page_heights():
    layout = PdfPageLayout([(600, 800), (500, 700)], zoom=1.0,
                           viewport_width=900, margin=24, spacing=16)
    page, point = layout.hit_test(450, 850, scroll_y=100)
    assert page == 1
    assert point.y() == pytest.approx(110.0)
```

Create a real two-page test PDF using `QPdfWriter` and `QPainter`, load it into the real view, assert `MultiPage`, page count, wheel-scroll range, and non-empty `QPdfDocument.getSelection` on known text. Add pure mapping tests for zoom and annotation rectangles.

- [ ] **Step 3: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view.py -q`

Expected: FAIL because `pdf_view` does not exist.

- [ ] **Step 4: Implement continuous view and overlays**

Subclass `QPdfView`, force `PageMode.MultiPage`, custom zoom, fixed document margins/spacing, and compute page rectangles from `QPdfDocument.pagePointSize`. On mouse release call `getSelection` once and emit normalized selection. Paint page tint, current selection, and annotation bounds after the base view. Wheel events must remain delegated to `QPdfView` and must not call selection extraction or storage.

- [ ] **Step 5: Run GREEN**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_view.py -q`

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt learning_assistant/ui/pdf_view.py tests_v2/test_pdf_view.py
git commit -m "feat: add continuous selectable PDF view"
```

### Task 5: PDF reader window, themes, and interaction

**Files:**
- Modify: `learning_assistant/core/settings.py` (`DEFAULT_SETTINGS` PDF keys and normalization)
- Create: `learning_assistant/ui/pdf_reader_window.py`
- Create: `tests_v2/test_pdf_reader_ui.py`

**Interfaces:**
- `PdfReaderWindow(controller, settings)` owns the view and translation panel.
- Methods: `open_file(path=None)`, `show_front()`, `has_active_selection()`, `translate_active_selection()`.
- Signals: `compact_mode_requested`, `settings_requested`.
- Stable theme IDs: `eye_care`, `paper`, `soft_gray`, `white`; invalid persisted values normalize to `eye_care`.

- [ ] **Step 1: Write failing UI and settings tests**

```python
def test_pdf_reader_defaults_to_eye_care_and_hides_phrase_panel(qtbot, ...):
    window = PdfReaderWindow(controller, settings)
    qtbot.addWidget(window)
    assert window.theme_combo.currentData() == "eye_care"
    assert window.phrase_panel.isHidden()

def test_translation_partial_is_visible_before_phrase_analysis(...):
    controller.translation_partial.emit("快速译文")
    assert window.translation.toPlainText() == "快速译文"
    assert window.phrase_panel.isHidden()
    controller.phrase_ready.emit(PdfPhrase("take part", "参加"))
    assert not window.phrase_panel.isHidden()
```

Also test theme persistence, highlight button routing, copy, retranslate, empty selection, and the 65/35 splitter default.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_reader_ui.py -q`

Expected: FAIL because the reader window and settings keys are missing.

- [ ] **Step 3: Implement the focused reader UI**

Use a horizontal `QSplitter`, compact toolbar, read-only translation widgets, and a phrase list that is absent from layout flow until data arrives. Theme changes update both the view and surrounding panels and save immediately. Do not add OCR, notes, batch translation, or extra navigation panels.

- [ ] **Step 4: Run GREEN plus settings regression**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_pdf_reader_ui.py tests_v2/test_settings.py -q`

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/core/settings.py learning_assistant/ui/pdf_reader_window.py tests_v2/test_pdf_reader_ui.py
git commit -m "feat: build PDF reading workspace"
```

### Task 6: Startup mode routing and contextual Alt+W

**Files:**
- Create: `learning_assistant/ui/mode_chooser.py`
- Modify: `learning_assistant/application.py`
- Modify: `tests_v2/test_ui_smoke.py`
- Create: `tests_v2/test_mode_router.py`

**Interfaces:**
- `ModeChooser` signals `compact_requested` and `pdf_requested`.
- `ApplicationModeRouter.show_chooser()`, `.show_compact()`, `.show_pdf()` lazily create and show one mode window while hiding the other.
- `LearningAssistantApplication._hotkey("selection")` first checks `pdf_window.isVisible()` and `pdf_window.has_active_selection()`; only then routes internally, otherwise calls existing `SelectionService.request()`.

- [ ] **Step 1: Write failing lazy-routing and fallback tests**

```python
def test_alt_w_prefers_visible_pdf_selection(application):
    pdf_window = FakePdfWindow(visible=True, active_selection=True)
    application.mode_router.pdf_window = pdf_window
    application._hotkey("selection")
    assert pdf_window.translate_calls == 1
    assert application.selection.request_calls == 0

def test_alt_w_falls_back_without_pdf_selection(application):
    application.mode_router.pdf_window = FakePdfWindow(visible=True, active_selection=False)
    application._hotkey("selection")
    assert application.selection.request_calls == 1
```

Use fakes at the window/service boundary; keep actual router state real. Test cold start shows only chooser, compact window retains its existing size, tray contains both mode actions, and closing chooser does not quit the application.

- [ ] **Step 2: Run RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_mode_router.py tests_v2/test_ui_smoke.py -q`

Expected: FAIL because mode chooser/router do not exist.

- [ ] **Step 3: Implement lazy routing and tray actions**

Move current eager `MainWindow` wiring behind compact-window creation without changing its public behavior. Create PDF controller/client/window only on first PDF selection. Keep one global hotkey service and one repository/settings instance. The tray “显示主窗口” action becomes “选择模式”, followed by explicit compact/PDF actions.

- [ ] **Step 4: Run GREEN plus selection regressions**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests_v2/test_mode_router.py tests_v2/test_ui_smoke.py tests_v2/test_selection.py tests_v2/test_hotkey_settings.py -q`

- [ ] **Step 5: Commit**

```powershell
git add learning_assistant/ui/mode_chooser.py learning_assistant/application.py tests_v2/test_mode_router.py tests_v2/test_ui_smoke.py
git commit -m "feat: route startup modes and PDF hotkey"
```

### Task 7: Documentation and final source verification

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Document development installation of PySide6 Addons, startup modes, PDF `Alt+W`, theme/highlight behavior, scanned-PDF limitation, and the intentional no-build/no-push handoff.

- [ ] **Step 1: Update user and architecture documentation**

Keep the instructions concise and state that only selected text is sent to the configured model. Do not claim OCR, cross-page selection, or packaging availability.

- [ ] **Step 2: Run fresh full verification**

```powershell
$env:PYTHONPATH=(Get-Location).Path
$env:QT_QPA_PLATFORM='offscreen'
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m compileall -q learning_assistant
```

Expected: all tests pass, compileall exits 0, and no warnings/errors are introduced.

- [ ] **Step 3: Run a local offscreen startup smoke check**

Run the application with a test-only timer that creates `LearningAssistantApplication`, asserts the chooser is visible and neither mode window is eagerly created, then quits. Run a second smoke that opens a generated two-page PDF, scrolls to page two, and verifies the current-page signal.

- [ ] **Step 4: Inspect the complete branch diff and requirements**

Confirm every spec requirement maps to a test or documented manual check. Run `git diff v1..HEAD --check` and verify no secrets, generated PDFs, user paths, caches, build output, or `.venv` files are tracked.

- [ ] **Step 5: Commit docs only**

```powershell
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: explain PDF reading mode"
```

- [ ] **Step 6: Stop before packaging or pushing**

Leave the verified feature in the local worktree and provide the exact local run command and acceptance checklist to the user. Do not run `build.bat`, do not create an EXE, and do not push `feature/pdf-reader`.
