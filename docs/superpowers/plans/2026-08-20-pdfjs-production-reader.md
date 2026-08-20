# PDF.js Production Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production PDF tab's manual Qt selection layer with the user-accepted PDF.js DOM selection adapter while preserving all reader workflows.

**Architecture:** A `PdfJsViewAdapter` owns one `QWebEngineView`, one narrow WebChannel bridge, and one secure loopback asset server per tab. PDF.js owns rendering and active selection; Python owns document identity, translation, persistence, settings, shortcuts, and lifecycle.

**Tech Stack:** Python 3.14, PySide6 6.10.1 QtWebEngine/QtWebChannel, PDF.js legacy 6.2.108, pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-08-20-pdfjs-production-reader-design.md`

## Global Constraints

- Work in `.worktrees/pdf-reader` on `feature/pdf-reader`; do not push or package.
- Preserve existing uncommitted `learning_assistant/ui/pdf_view.py`, `tests_v2/test_pdf_view.py`, and Qt Quick spike files.
- Use the existing `PdfReaderTab`/controller/domain interfaces; no LLM, cache, repository, or shortcut redesign.
- Use test-first RED → GREEN for every production behavior.
- Only Mozilla PDF.js 6.2.108 legacy runtime assets are vendored; include its license and omit maps/samples/debugger.

---

### Task 1: Production bridge and secure Range server

**Files:**
- Create: `learning_assistant/ui/pdfjs_bridge.py`
- Create: `learning_assistant/ui/pdfjs_server.py`
- Create: `tests_v2/test_pdfjs_bridge.py`
- Create: `tests_v2/test_pdfjs_server.py`

**Interfaces:**
- `BrowserPdfSelection(text, page_indices, page_index, start_index, end_index, bounds, can_annotate)`.
- `PdfJsBridge.commit(raw_payload)` emits one `PdfTextSelection` or clears the selection; malformed input emits `bridge_error`.
- `PdfJsAssetServer(asset_root, document_path, extra_files)` serves fixed local assets and one tokenized document with GET/HEAD/Range.

- [ ] Write bridge and server behavior tests with literal payloads/bytes.
- [ ] Run the focused tests and observe missing-module RED.
- [ ] Implement minimal validated bridge and streaming server.
- [ ] Run focused GREEN and refactor without changing behavior.

### Task 2: Production PDF.js view adapter

**Files:**
- Create: `learning_assistant/ui/pdfjs_view.py`
- Create: `learning_assistant/ui/pdfjs_reader.css`
- Create: `tests_v2/test_pdfjs_view.py`

**Interfaces:**
- `PdfJsViewAdapter(QWidget)` exposes the current reader view signals/methods and `document_key`.
- JavaScript reports document/page/scale/error/selection events and renders persistent annotations.
- `load_file()` validates local PDF synchronously, starts an isolated server, and emits `document_loaded` only after PDF.js parses it.

- [ ] Write adapter contract and real-WebEngine tests for loading, selection, zoom, theme, page, annotations, and close.
- [ ] Run RED against the absent adapter.
- [ ] Implement WebChannel injection, lifecycle, zoom/theme/page routing, annotation rendering, and Ctrl-wheel zoom.
- [ ] Run focused GREEN with `QTWEBENGINE_DISABLE_SANDBOX=1` only in the Codex test environment.

### Task 3: Switch the formal reading tab

**Files:**
- Modify: `learning_assistant/ui/pdf_reader_tab.py`
- Modify: `tests_v2/test_pdf_reader_ui.py`
- Modify: `tests_v2/test_pdf_tabs.py`

**Interfaces:**
- `PdfReaderTab.pdf_view` becomes `PdfJsViewAdapter` without changing callers.
- Translation remains enabled for every valid selection; marking is enabled only for stable single-page indices.

- [ ] Add failing integration assertions that the tab constructs the adapter and preserves zoom/translation/mark behavior.
- [ ] Run RED while the tab still constructs `SelectablePdfView`.
- [ ] Switch the import/construction and connect selection feedback.
- [ ] Run UI, multi-tab, mode-router, focus-mode, and shortcut GREEN.

### Task 4: Vendor runtime assets and record licensing

**Files:**
- Create: `assets/pdfjs-6.2.108-legacy/**`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- `learning_assistant.core.paths.project_root()/assets/pdfjs-6.2.108-legacy` is the default runtime root.
- License and source URL are present beside the vendored assets and in third-party notices.

- [ ] Copy only required official legacy runtime files and verify `viewer.html`, `pdf.mjs`, and `pdf.worker.mjs` exist.
- [ ] Add notices and source-run documentation; do not run packaging.
- [ ] Run asset-backed production tests from the formal location.

### Task 5: Full verification and source handoff

**Files:**
- Modify only files from Tasks 1–4 if verification reveals a scoped defect.

- [ ] Run PDF.js focused tests.
- [ ] Run the complete pytest suite.
- [ ] Run compileall and `git diff --check`.
- [ ] Inspect the complete diff and confirm no PDF, screenshot, secret, cache, package, or unrelated file was added.
- [ ] Start `main.py` for user validation; do not build or push.
