"""Production PDF.js reader adapter behind the existing QWidget contract."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODevice, QPointF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QResizeEvent, QWheelEvent
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from learning_assistant.core.paths import project_root
from learning_assistant.domain.pdf_models import PdfAnnotation, PdfTextSelection
from learning_assistant.services.pdf_text import document_key
from learning_assistant.ui.pdf_themes import READING_THEMES
from learning_assistant.ui.pdfjs_bridge import PdfJsBridge
from learning_assistant.ui.pdfjs_server import PdfJsAssetServer


logger = logging.getLogger(__name__)

PDFJS_VERSION = "6.2.108"
PDFJS_ASSET_ROOT = project_root() / "assets" / f"pdfjs-{PDFJS_VERSION}-legacy"
_READER_CSS = project_root() / "assets" / "linguaspark" / "pdfjs_reader.css"

_ANNOTATION_COLORS = {
    "yellow": "rgba(250, 204, 21, 0.42)",
    "green": "rgba(74, 222, 128, 0.38)",
    "pink": "rgba(244, 114, 182, 0.38)",
}


_READER_HOOK = r"""
(() => {
    function install(channel) {
        const bridge = channel.objects.pdfJsBridge;
        let annotations = {};
        let observedDocument = null;
        let requestedScale = 1;
        let requestedScaleMode = "custom";
        let requestedPage = null;
        let keepSelectionForActions = false;
        let hasCommittedSelection = false;
        let selectionSignature = null;
        let citation = null;
        let citationTimer = null;

        const style = document.createElement("link");
        style.rel = "stylesheet";
        style.href = "/linguaspark-reader.css";
        document.documentElement.appendChild(style);

        function application() {
            return globalThis.PDFViewerApplication;
        }

        function pageElement(pageIndex) {
            return document.querySelector(
                `.pdfViewer .page[data-page-number="${pageIndex + 1}"]`
            );
        }

        function pageScale(pageIndex) {
            const view = application()?.pdfViewer?.getPageView(pageIndex);
            return Number(view?.viewport?.scale || application()?.pdfViewer?.currentScale || 1);
        }

        function indicesForRange(pageIndex, range) {
            const layer = pageElement(pageIndex)?.querySelector(".textLayer");
            if (!layer || !layer.contains(range.startContainer) || !layer.contains(range.endContainer))
                return {start: -1, end: -1};
            try {
                const prefix = document.createRange();
                prefix.selectNodeContents(layer);
                prefix.setEnd(range.startContainer, range.startOffset);
                const start = prefix.toString().length;
                return {start, end: start + range.toString().length};
            } catch (_error) {
                return {start: -1, end: -1};
            }
        }

        function reportSelection(event) {
            const selection = window.getSelection();
            if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
                if (keepSelectionForActions)
                    return;
                hasCommittedSelection = false;
                selectionSignature = null;
                const page = event?.target?.closest?.(".pdfViewer .page") || null;
                if (page) {
                    const layer = page.querySelector(".textLayer");
                    bridge.empty(Boolean(layer?.textContent?.trim()));
                } else {
                    bridge.commit(JSON.stringify({text: "", pages: [], rects: []}));
                }
                return;
            }
            const text = selection.toString();
            keepSelectionForActions = false;
            hasCommittedSelection = true;
            const pages = new Set();
            const rects = [];
            const geometry = new Map();
            for (let index = 0; index < selection.rangeCount; index += 1) {
                const range = selection.getRangeAt(index);
                const ancestor = range.commonAncestorContainer;
                const root = ancestor.nodeType === Node.TEXT_NODE ? ancestor.parentNode : ancestor;
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    const parent = node.parentElement;
                    // PDF.js moves a large endOfContent helper during dragging.
                    // Only glyph ranges belong in a saved highlight.
                    if (!node.length || !parent?.closest('.textLayer')
                            || parent.closest('.endOfContent') || !range.intersectsNode(node))
                        continue;
                    const page = parent.closest('.pdfViewer .page');
                    if (!page)
                        continue;
                    const pageIndex = Number(page.dataset.pageNumber) - 1;
                    if (!Number.isInteger(pageIndex) || pageIndex < 0)
                        continue;
                    const glyphs = document.createRange();
                    glyphs.setStart(node, node === range.startContainer ? range.startOffset : 0);
                    glyphs.setEnd(node, node === range.endContainer ? range.endOffset : node.length);
                    for (const rect of glyphs.getClientRects()) {
                        if (rect.width <= 0 || rect.height <= 0)
                            continue;
                        if (!geometry.has(pageIndex))
                            geometry.set(pageIndex, {bounds: page.getBoundingClientRect(), scale: pageScale(pageIndex)});
                        const {bounds, scale} = geometry.get(pageIndex);
                        pages.add(pageIndex);
                        rects.push({
                            page: pageIndex,
                            // Absolute annotation children start inside the page border.
                            x: (rect.left - bounds.left - page.clientLeft) / scale,
                            y: (rect.top - bounds.top - page.clientTop) / scale,
                            width: rect.width / scale,
                            height: rect.height / scale,
                        });
                    }
                }
            }
            const pageList = [...pages];
            const page = pageList.length ? pageList[0] : -1;
            const indices = pageList.length === 1
                ? indicesForRange(page, selection.getRangeAt(0))
                : {start: -1, end: -1};
            const signature = JSON.stringify([text, pageList, indices.start, indices.end]);
            if (signature === selectionSignature)
                return;
            selectionSignature = signature;
            bridge.commit(JSON.stringify({
                text,
                pages: pageList,
                page,
                start: indices.start,
                end: indices.end,
                rects,
            }));
        }

        function mergedHighlightRects(raw) {
            const rects = raw.map(rect => ({left: rect.left, top: rect.top,
                right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height}))
                .filter(rect => Object.values(rect).every(Number.isFinite) && rect.width > 0 && rect.height > 0);
            const parent = rects.map((_, index) => index);
            const root = index => {
                while (parent[index] !== index) index = parent[index];
                return index;
            };
            // Join actual neighboring glyphs, including subscripts, before
            // painting. Separate lines and distant columns stay separate.
            for (let first = 0; first < rects.length; first++) {
                for (let second = first + 1; second < rects.length; second++) {
                    const a = rects[first], b = rects[second];
                    const xOverlap = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                    const yOverlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                    const smallHeight = Math.min(a.height, b.height);
                    const sameLine = yOverlap >= smallHeight * 0.3 && -xOverlap <= Math.max(2, smallHeight * 0.3);
                    const script = -yOverlap <= Math.max(1, smallHeight * 0.2)
                        && xOverlap >= Math.min(a.width, b.width) * 0.15
                        && Math.abs((a.top + a.bottom - b.top - b.bottom) / 2) <= Math.max(a.height, b.height) * 0.9;
                    if (sameLine || script) parent[root(second)] = root(first);
                }
            }
            const groups = new Map();
            rects.forEach((rect, index) => {
                const id = root(index), previous = groups.get(id);
                groups.set(id, previous ? {left: Math.min(previous.left, rect.left), top: Math.min(previous.top, rect.top),
                    right: Math.max(previous.right, rect.right), bottom: Math.max(previous.bottom, rect.bottom)} : rect);
            });
            return [...groups.values()].map(rect => ({left:rect.left, top:rect.top, right:rect.right,
                bottom:rect.bottom, width:rect.right - rect.left, height:rect.bottom - rect.top}))
                .sort((a, b) => a.top - b.top || a.left - b.left);
        }

        function renderPageAnnotations(pageIndex) {
            const page = pageElement(pageIndex);
            if (!page)
                return;
            page.querySelectorAll(".linguaspark-annotation-layer").forEach(item => item.remove());
            const items = annotations[String(pageIndex)] || [];
            if (!items.length)
                return;
            const scale = pageScale(pageIndex);
            const layer = document.createElement("div");
            layer.className = "linguaspark-annotation-layer";
            for (const item of items) {
                const rects = (item.bounds || []).map(bounds => {
                    const [x, y, width, height] = bounds.map(Number);
                    return {left:x * scale, top:y * scale, right:(x + width) * scale,
                        bottom:(y + height) * scale, width:width * scale, height:height * scale};
                });
                for (const rect of mergedHighlightRects(rects)) {
                    const mark = document.createElement("div");
                    mark.className = "linguaspark-annotation";
                    mark.style.left = `${rect.left}px`;
                    mark.style.top = `${rect.top}px`;
                    mark.style.width = `${rect.width}px`;
                    mark.style.height = `${rect.height}px`;
                    mark.style.backgroundColor = item.color;
                    layer.appendChild(mark);
                }
            }
            page.appendChild(layer);
        }

        function renderAnnotations() {
            for (const page of document.querySelectorAll(".pdfViewer .page")) {
                const index = Number(page.dataset.pageNumber) - 1;
                if (Number.isInteger(index) && index >= 0)
                    renderPageAnnotations(index);
            }
        }

        function clearCitation() {
            if (!citation)
                return;
            citation = null;
            clearTimeout(citationTimer);
            document.querySelectorAll('.linguaspark-citation-layer').forEach(item => item.remove());
            document.querySelectorAll('.linguaspark-citation-page').forEach(item =>
                item.classList.remove('linguaspark-citation-page'));
        }

        function normalizedCitationText(text) {
            return text.normalize('NFKC').toLowerCase()
                .replace(/[\u2018\u2019\u02bc]/g, "'").replace(/[\u201c\u201d]/g, '"')
                .replace(/[\u2010-\u2015]/g, '-').replace(/[\s\u00ad\u200b]/gu, '');
        }

        function citationRange(layer, quote) {
            const trimmed = quote.trim();
            const wrappers = {'"':'"', "'":"'", '\u201c':'\u201d', '\u2018':'\u2019', '`':'`'};
            const unwrapped = wrappers[trimmed[0]] === trimmed[trimmed.length - 1]
                ? trimmed.slice(1, -1).trim() : trimmed;
            const needles = [...new Set([quote, unwrapped].map(normalizedCitationText))].filter(text => text.length >= 4);
            if (!needles.length)
                return null;
            const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
            let text = '';
            const positions = [];
            while (walker.nextNode()) {
                const node = walker.currentNode;
                let offset = 0;
                for (const character of node.nodeValue) {
                    const normalized = normalizedCitationText(character);
                    text += normalized;
                    for (let index = 0; index < normalized.length; index += 1)
                        positions.push({node, start: offset, end: offset + character.length});
                    offset += character.length;
                }
            }
            function locate(value, mapping) {
                for (const needle of needles) {
                    const start = value.indexOf(needle);
                    // Do not guess between repeated occurrences.
                    if (start < 0 || value.indexOf(needle, start + 1) >= 0)
                        continue;
                    const first = mapping[start], last = mapping[start + needle.length - 1];
                    const range = document.createRange();
                    range.setStart(first.node, first.start);
                    range.setEnd(last.node, last.end);
                    return range;
                }
                return null;
            }
            const exact = locate(text, positions);
            if (exact)
                return exact;
            // PDF prose may split a word across lines using a visible hyphen.
            // Remove only trailing prose hyphens, not mathematical minus signs
            // or hyphens within the same line, and retain glyph offset mapping.
            let joined = '';
            const joinedPositions = [];
            positions.forEach((position, index) => {
                const next = positions[index + 1];
                if (text[index] === '-' && next && next.node !== position.node
                        && /[a-z]{2}-\s*$/i.test(position.node.nodeValue)
                        && /^\s*[a-z]{2}/.test(next.node.nodeValue)) {
                    const a = position.node.parentElement.getBoundingClientRect();
                    const b = next.node.parentElement.getBoundingClientRect();
                    if (b.top > a.top + Math.min(a.height, b.height) * 0.5 && b.left < a.right)
                        return;
                }
                joined += text[index];
                joinedPositions.push(position);
            });
            return locate(joined, joinedPositions);
        }

        function citationScroll(target, rect) {
            const container = document.querySelector('#viewerContainer');
            if (!container)
                return;
            const viewport = container.getBoundingClientRect();
            const top = viewport.top + container.clientTop + 16;
            const bottom = viewport.top + container.clientTop + container.clientHeight - 16;
            // Only reveal vertically when needed; never pan the document or
            // move a passage that is already visible in the reading viewport.
            if (rect.top < top)
                container.scrollTop += rect.top - top;
            else if (rect.bottom > bottom)
                container.scrollTop += rect.bottom - bottom;
            container.scrollLeft = target.scrollLeft;
        }

        function renderCitation() {
            const target = citation;
            if (!target)
                return;
            const page = pageElement(target.page);
            if (!page)
                return;
            page.querySelectorAll('.linguaspark-citation-layer').forEach(item => item.remove());
            const textLayer = page.querySelector('.textLayer');
            const range = textLayer && target.quote ? citationRange(textLayer, target.quote) : null;
            const rects = range ? mergedHighlightRects([...range.getClientRects()]) : [];
            if (!rects.length) {
                page.classList.add('linguaspark-citation-page');
                return;
            }
            page.classList.remove('linguaspark-citation-page');
            const bounds = page.getBoundingClientRect();
            const layer = document.createElement('div');
            layer.className = 'linguaspark-citation-layer';
            for (const rect of rects) {
                const mark = document.createElement('div');
                mark.className = 'linguaspark-citation';
                mark.style.left = `${rect.left - bounds.left - page.clientLeft}px`;
                mark.style.top = `${rect.top - bounds.top - page.clientTop}px`;
                mark.style.width = `${rect.width}px`;
                mark.style.height = `${rect.height}px`;
                layer.appendChild(mark);
            }
            page.appendChild(layer);
            if (!target.positioned) {
                target.positioned = true;
                citationScroll(target, rects[0]);
                clearTimeout(citationTimer);
                citationTimer = setTimeout(() => { if (citation === target) clearCitation(); }, 4000);
            }
        }

        globalThis.linguaReader = {
            setTheme(_themeId, paper, workspace) {
                document.documentElement.style.setProperty("--linguaspark-paper", paper);
                document.documentElement.style.setProperty("--linguaspark-workspace", workspace);
            },
            setAnnotations(raw) {
                try {
                    annotations = JSON.parse(raw) || {};
                } catch (_error) {
                    annotations = {};
                }
                renderAnnotations();
            },
            setZoomFactor(value) {
                const viewer = application()?.pdfViewer;
                requestedScale = Math.max(0.5, Math.min(3.0, Number(value)));
                requestedScaleMode = "custom";
                if (viewer) {
                    // Keep the last painted canvas during a wheel/toolbar burst,
                    // then replace it once with the final sharp render.
                    viewer.updateScale({
                        scaleFactor: requestedScale / viewer.currentScale,
                        drawingDelay: 150,
                    });
                }
            },
            fitToWidth() {
                const viewer = application()?.pdfViewer;
                requestedScaleMode = "page-width";
                if (viewer)
                    viewer.currentScaleValue = "page-width";
            },
            clearSelection() {
                keepSelectionForActions = false;
                window.getSelection()?.removeAllRanges();
            },
            viewportChanged(generation) {
                application()?.pdfViewer?.update();
                // The first frame applies the new viewport; the next one
                // lets Chromium submit its replacement compositor surface.
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    bridge.frame_ready(generation);
                }));
            },
            goToPage(pageIndex) {
                clearCitation();
                const app = application();
                const count = Number(app?.pdfDocument?.numPages || 0);
                requestedPage = Math.max(0, Math.trunc(Number(pageIndex)));
                if (app?.pdfViewer?.pagesCount && count) {
                    app.pdfViewer.scrollPageIntoView({pageNumber: Math.min(requestedPage + 1, count)});
                }
            },
            revealCitation(pageIndex, quote) {
                clearCitation();
                requestedPage = pageIndex;
                const container = document.querySelector('#viewerContainer');
                const target = citation = {page: pageIndex, quote, positioned: false, scrollLeft:container?.scrollLeft || 0};
                const page = pageElement(pageIndex);
                if (container && page) {
                    const viewport = container.getBoundingClientRect();
                    const bounds = page.getBoundingClientRect();
                    if (bounds.bottom <= viewport.top || bounds.top >= viewport.bottom) {
                        container.scrollTop += bounds.top - viewport.top - container.clientTop;
                        container.scrollLeft = target.scrollLeft;
                    }
                }
                application()?.pdfViewer?.update();
                // Allow a lazy target page to finish its text layer before
                // starting the four-second passage highlight lifetime.
                citationTimer = setTimeout(() => { if (citation === target) clearCitation(); }, 12000);
                renderCitation();
            },
            renderAnnotations,
        };

        window.addEventListener("blur", () => {
            // Focus may leave before Chromium receives mouseup.
            reportSelection();
            // Remove the browser's blue highlight immediately when the user
            // moves to Qt controls, but retain the committed text for actions.
            keepSelectionForActions = true;
            window.getSelection()?.removeAllRanges();
        });
        document.addEventListener("pointerdown", event => {
            if (event.target?.closest?.('#viewerContainer'))
                clearCitation();
            if (event.button !== 0)
                return;
            keepSelectionForActions = false;
            if (!event.shiftKey)
                window.getSelection()?.removeAllRanges();
        }, true);
        document.addEventListener("selectionchange", () => {
            const selection = window.getSelection();
            if (hasCommittedSelection && !keepSelectionForActions && (!selection || selection.isCollapsed)) {
                hasCommittedSelection = false;
                selectionSignature = null;
                bridge.commit(JSON.stringify({text: "", pages: [], rects: []}));
            }
        });
        document.addEventListener('wheel', clearCitation, {passive: true});
        document.addEventListener('keydown', event => {
            if (['PageDown','PageUp','Home','End','ArrowDown','ArrowUp','ArrowLeft','ArrowRight'].includes(event.key))
                clearCitation();
        });

        document.addEventListener(
            "mouseup",
            event => setTimeout(() => reportSelection(event), 0),
            true
        );
        document.addEventListener("keyup", event => {
            if (event.key.startsWith("Arrow") || event.key === "Shift")
                setTimeout(() => reportSelection(event), 0);
        }, true);

        function bindViewer() {
            const app = application();
            if (!app || !app.eventBus) {
                setTimeout(bindViewer, 25);
                return;
            }
            const reportReady = () => {
                if (!app.pdfDocument || app.pdfDocument === observedDocument)
                    return;
                observedDocument = app.pdfDocument;
                bridge.ready(Number(app.pagesCount || app.pdfDocument.numPages || 0));
                setTimeout(renderAnnotations, 0);
            };
            app.eventBus.on("documentloaded", reportReady);
            app.eventBus.on("pagesinit", () => {
                if (requestedScaleMode === "page-width")
                    app.pdfViewer.currentScaleValue = "page-width";
                else
                    app.pdfViewer.currentScale = requestedScale;
                if (requestedPage !== null)
                    globalThis.linguaReader.goToPage(requestedPage);
                setTimeout(renderAnnotations, 0);
            });
            app.eventBus.on("pagechanging", event => {
                bridge.page_changed(Math.max(0, Number(event.pageNumber || 1) - 1));
            });
            app.eventBus.on("scalechanging", event => {
                bridge.scale_changed(Number(event.scale || app.pdfViewer.currentScale || 1));
                setTimeout(renderAnnotations, 0);
            });
            app.eventBus.on("pagerendered", event => {
                renderPageAnnotations(Math.max(0, Number(event.pageNumber || 1) - 1));
                renderCitation();
            });
            app.eventBus.on('textlayerrendered', renderCitation);
            app.eventBus.on("documenterror", event => {
                bridge.failed(String(event?.message || event?.reason?.message || "PDF document failed to load"));
            });
            reportReady();
        }
        bindViewer();
    }

    function connect() {
        if (!document.documentElement || !globalThis.qt || !qt.webChannelTransport) {
            setTimeout(connect, 25);
            return;
        }
        new QWebChannel(qt.webChannelTransport, install);
    }
    connect();
})();
"""


def _web_channel_source() -> str:
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt WebChannel JavaScript resource is unavailable")
    try:
        return bytes(resource.readAll()).decode("utf-8")
    finally:
        resource.close()


class _ReaderPage(QWebEnginePage):
    console_message = Signal(str)

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        rendered = f"{level.name}: {source_id}:{line_number}: {message}"
        self.console_message.emit(rendered)
        logger.debug("PDF.js: %s", rendered)


class PdfJsViewAdapter(QWebEngineView):
    """PDF.js viewer with the public API expected by ``PdfReaderTab``."""

    selection_changed = Signal(object)
    selection_feedback = Signal(str)
    document_loaded = Signal(str, int)
    load_failed = Signal(str)
    current_page_changed = Signal(int)
    zoomFactorChanged = Signal(float)
    console_message = Signal(str)

    def __init__(self, asset_root: Path = PDFJS_ASSET_ROOT, parent=None) -> None:
        super().__init__(parent)
        page = _ReaderPage(self)
        page.console_message.connect(self.console_message)
        self.setPage(page)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        self._asset_root = Path(asset_root)
        self._server: PdfJsAssetServer | None = None
        self._path: Path | None = None
        self._document_key = ""
        self._selection: PdfTextSelection | None = None
        self._annotations: list[PdfAnnotation] = []
        self._theme_id = "eye_care"
        self._zoom_factor = 1.0
        self._zoom_mode = QPdfView.ZoomMode.Custom
        self._ready = False
        self._pending_page: int | None = None
        self._page_count = 0
        self._selection_drag_active = False
        self._viewport_generation = 0
        self._viewport_preview = QLabel(self)
        self._viewport_preview.setScaledContents(True)
        self._viewport_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._viewport_preview.hide()
        self._viewport_timer = QTimer(self)
        self._viewport_timer.setSingleShot(True)
        self._viewport_timer.setInterval(40)
        self._viewport_timer.timeout.connect(self._request_viewport_frame)

        self._bridge = PdfJsBridge(self)
        self._bridge.selection_changed.connect(self._selection_received)
        self._bridge.empty_selection.connect(self._empty_selection)
        self._bridge.document_ready.connect(self._document_ready)
        self._bridge.current_page_changed.connect(self.current_page_changed)
        self._bridge.zoom_changed.connect(self._browser_zoom_changed)
        self._bridge.document_error.connect(self._document_error)
        self._bridge.bridge_error.connect(self.load_failed)
        self._bridge.viewport_ready.connect(self._viewport_frame_ready)

        self._channel = QWebChannel(self.page())
        self._channel.registerObject("pdfJsBridge", self._bridge)
        self.page().setWebChannel(self._channel)

        injection = QWebEngineScript()
        injection.setName("LinguaSpark PDF.js reader bridge")
        injection.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        injection.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        injection.setRunsOnSubFrames(False)
        injection.setSourceCode(_web_channel_source() + "\n" + _READER_HOOK)
        self.page().scripts().insert(injection)
        self.loadFinished.connect(self._load_finished)
        QApplication.instance().installEventFilter(self)

    @property
    def document_key(self) -> str:
        return self._document_key

    def current_selection(self) -> PdfTextSelection | None:
        return self._selection

    def load_file(self, path: str | Path) -> bool:
        candidate = Path(path).resolve()
        if not candidate.is_file():
            self.load_failed.emit("找不到此 PDF 文件")
            return False
        try:
            with candidate.open("rb") as source:
                signature = source.read(5)
        except OSError:
            self.load_failed.emit("无法读取此 PDF")
            return False
        if signature != b"%PDF-":
            self.load_failed.emit("所选文件不是有效的 PDF")
            return False

        self.close_document()
        try:
            server = PdfJsAssetServer(
                self._asset_root,
                candidate,
                {"/linguaspark-reader.css": _READER_CSS},
            ).start()
        except (OSError, ValueError) as error:
            logger.warning("Unable to start PDF.js reader: %s", error)
            self.load_failed.emit("PDF 阅读组件资源缺失")
            return False
        self._server = server
        self._path = candidate
        self._document_key = document_key(candidate)
        self._selection = None
        self._annotations = []
        self._zoom_factor = 1.0
        self._zoom_mode = QPdfView.ZoomMode.Custom
        self._ready = False
        self.load(QUrl(server.viewer_url))
        return True

    def close_document(self) -> None:
        self._selection_drag_active = False
        self._viewport_timer.stop()
        self._viewport_generation += 1
        self._viewport_preview.hide()
        self._viewport_preview.clear()
        self.stop()
        server, self._server = self._server, None
        self._ready = False
        self._path = None
        self._document_key = ""
        self._selection = None
        self._annotations = []
        self._pending_page = None
        self._page_count = 0
        if server is not None:
            self.setUrl(QUrl("about:blank"))
            server.stop()

    def set_pdf_password(self, _password: str) -> bool:
        self.load_failed.emit("加密 PDF 请在阅读器的密码提示框中输入密码")
        return False

    def set_annotations(self, annotations: list[PdfAnnotation]) -> None:
        self._annotations = list(annotations)
        payload: dict[str, list[dict[str, object]]] = {}
        for annotation in self._annotations:
            payload.setdefault(str(annotation.page_index), []).append(
                {
                    "color": _ANNOTATION_COLORS.get(
                        annotation.color, _ANNOTATION_COLORS["yellow"]
                    ),
                    "bounds": [list(bound) for bound in annotation.bounds],
                }
            )
        self._run_reader(
            f"linguaReader.setAnnotations({json.dumps(json.dumps(payload))});"
        )

    def clear_selection(self) -> None:
        self._selection_received(None)
        self._run_reader("linguaReader.clearSelection();")

    def set_reading_theme(self, theme_id: str) -> None:
        self._theme_id = theme_id if theme_id in READING_THEMES else "eye_care"
        paper = READING_THEMES[self._theme_id]
        workspace = self._workspace_color(paper)
        # Qt's native surface must also have an opaque background while the
        # Chromium compositor is resizing during a fullscreen transition.
        self.page().setBackgroundColor(QColor(workspace))
        self._run_reader(
            "linguaReader.setTheme("
            f"{json.dumps(self._theme_id)}, {json.dumps(paper)}, {json.dumps(workspace)}"
            ");"
        )

    @staticmethod
    def _workspace_color(paper: str) -> str:
        red, green, blue = (
            int(paper[index : index + 2], 16) for index in (1, 3, 5)
        )
        return "#{:02X}{:02X}{:02X}".format(
            max(0, red - 11), max(0, green - 10), max(0, blue - 10)
        )

    def zoomFactor(self) -> float:
        return self._zoom_factor

    def zoomMode(self):
        return self._zoom_mode

    def set_zoom_factor(self, value: float) -> None:
        target = round(max(0.5, min(3.0, float(value))), 2)
        self._zoom_mode = QPdfView.ZoomMode.Custom
        self._set_zoom_state(target)
        self._run_reader(f"linguaReader.setZoomFactor({target!r});")

    def adjust_zoom(self, steps: int) -> None:
        if steps:
            self.set_zoom_factor(self._zoom_factor + int(steps) * 0.1)

    def fit_to_width(self) -> None:
        self._zoom_mode = QPdfView.ZoomMode.FitToWidth
        self._run_reader("linguaReader.fitToWidth();")

    def go_to_page(self, page_index: int) -> bool:
        if (not isinstance(page_index, int) or isinstance(page_index, bool)
                or page_index < 0 or self._path is None):
            return False
        self._pending_page = page_index
        if self._ready:
            target = min(page_index, max(0, self._page_count - 1))
            self._run_reader(f"linguaReader.goToPage({target});")
            self._pending_page = None
        return True

    def reveal_citation(self, page_index: int, quote: str = "") -> bool:
        """Reveal a cited passage without changing selection or saved marks."""
        if (not self._ready or not isinstance(page_index, int) or isinstance(page_index, bool)
                or not 0 <= page_index < self._page_count or not isinstance(quote, str) or len(quote) > 500):
            return False
        self._run_reader(f"linguaReader.revealCitation({page_index}, {json.dumps(quote)});")
        return True

    def _adjust_zoom_from_wheel(
        self,
        delta: int,
        modifiers: Qt.KeyboardModifier,
    ) -> bool:
        if modifiers & Qt.KeyboardModifier.ControlModifier and delta:
            self.adjust_zoom(1 if delta > 0 else -1)
            return True
        return False

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._adjust_zoom_from_wheel(event.angleDelta().y(), event.modifiers()):
            event.accept()
            return
        super().wheelEvent(event)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                        QEvent.Type.MouseMove, QEvent.Type.Wheel):
            return super().eventFilter(watched, event)
        in_view = isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if in_view:
                self._selection_drag_active = True
        elif self._selection_drag_active:
            if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._selection_drag_active = False
                if not in_view:
                    self._finish_selection_drag(event)
            elif (in_view and kind in (QEvent.Type.MouseMove, QEvent.Type.Wheel)
                  and not event.buttons() & Qt.MouseButton.LeftButton):
                self._selection_drag_active = False
                self._finish_selection_drag(event)
        return super().eventFilter(watched, event)

    def _finish_selection_drag(self, event) -> None:
        # A release delivered to another Qt widget never reaches Blink. Send a
        # native release too: a JavaScript mouseup cannot stop its autoscroll.
        target = self.focusProxy() or self
        point = target.mapFromGlobal(event.globalPosition().toPoint())
        point.setX(max(1, min(target.width() - 2, point.x())))
        point.setY(max(1, min(target.height() - 2, point.y())))
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(point),
            QPointF(target.mapToGlobal(point)), Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton, event.modifiers(),
        )
        QApplication.sendEvent(target, release)

    def begin_viewport_transition(self) -> None:
        """Keep a complete frame visible while the native PDF viewport resizes."""
        if not self._ready or not self.isVisible():
            return
        if self._viewport_preview.isHidden():
            frame = self.grab()
            if frame.isNull():
                return
            self._viewport_preview.setPixmap(frame)
        self._viewport_preview.setGeometry(self.rect())
        self._viewport_preview.show()
        self._viewport_preview.raise_()
        self._viewport_generation += 1
        self._viewport_timer.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_viewport_preview") and not self._viewport_preview.isHidden():
            self._viewport_preview.setGeometry(self.rect())
            self._viewport_preview.raise_()
            self._viewport_generation += 1
            self._viewport_timer.start()

    def _request_viewport_frame(self) -> None:
        self._run_reader(f"linguaReader.viewportChanged({self._viewport_generation});")

    def _viewport_frame_ready(self, generation: int) -> None:
        if generation != self._viewport_generation or self._viewport_timer.isActive():
            return
        self._viewport_preview.hide()
        self._viewport_preview.clear()

    def _run_reader(self, statement: str) -> None:
        if self._ready:
            self.page().runJavaScript(
                "if (globalThis.linguaReader) { " + statement + " }"
            )

    def _selection_received(self, selection: PdfTextSelection | None) -> None:
        self._selection = selection
        self.selection_changed.emit(selection)

    def _empty_selection(self, has_selectable_text: bool) -> None:
        self._selection_received(None)
        if not has_selectable_text:
            self.selection_feedback.emit(
                "当前页面没有可选择文字，扫描版 PDF 暂不支持 OCR"
            )

    def _document_ready(self, page_count: int) -> None:
        if self._server is None or self._path is None:
            return
        self._ready = True
        self._page_count = page_count
        self.set_reading_theme(self._theme_id)
        self.set_annotations(self._annotations)
        self.set_zoom_factor(self._zoom_factor)
        if self._pending_page is not None:
            self.go_to_page(self._pending_page)
        self.document_loaded.emit(self._document_key, page_count)

    def _browser_zoom_changed(self, factor: float) -> None:
        self._set_zoom_state(round(max(0.5, min(3.0, factor)), 2))

    def _set_zoom_state(self, factor: float) -> None:
        if abs(factor - self._zoom_factor) < 0.001:
            return
        self._zoom_factor = factor
        self.zoomFactorChanged.emit(factor)

    def _document_error(self, message: str) -> None:
        rendered = str(message or "").casefold()
        if "password" in rendered:
            self.load_failed.emit("此 PDF 需要密码")
        else:
            self.load_failed.emit("无法打开此 PDF")

    def _load_finished(self, succeeded: bool) -> None:
        if not succeeded and self._server is not None:
            self.load_failed.emit("PDF 阅读组件加载失败")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.close_document()
        super().closeEvent(event)
