"""Production PDF.js reader adapter behind the existing QWidget contract."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QUrl, Qt, Signal
from PySide6.QtGui import QCloseEvent, QWheelEvent
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from learning_assistant.core.paths import project_root
from learning_assistant.domain.pdf_models import PdfAnnotation, PdfTextSelection
from learning_assistant.services.pdf_text import document_key
from learning_assistant.ui.pdf_themes import READING_THEMES
from learning_assistant.ui.pdfjs_bridge import PdfJsBridge
from learning_assistant.ui.pdfjs_server import PdfJsAssetServer


logger = logging.getLogger(__name__)

PDFJS_VERSION = "6.2.108"
PDFJS_ASSET_ROOT = project_root() / "assets" / f"pdfjs-{PDFJS_VERSION}-legacy"
_READER_CSS = Path(__file__).with_name("pdfjs_reader.css")

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

        function pageForRect(rect) {
            let best = null;
            let bestArea = 0;
            for (const page of document.querySelectorAll(".pdfViewer .page")) {
                const bounds = page.getBoundingClientRect();
                const width = Math.max(0,
                    Math.min(rect.right, bounds.right) - Math.max(rect.left, bounds.left));
                const height = Math.max(0,
                    Math.min(rect.bottom, bounds.bottom) - Math.max(rect.top, bounds.top));
                const area = width * height;
                if (area > bestArea) {
                    best = {element: page, bounds};
                    bestArea = area;
                }
            }
            return best;
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
            const pages = new Set();
            const rects = [];
            for (let index = 0; index < selection.rangeCount; index += 1) {
                const range = selection.getRangeAt(index);
                for (const rect of range.getClientRects()) {
                    if (rect.width <= 0 || rect.height <= 0)
                        continue;
                    const page = pageForRect(rect);
                    if (!page)
                        continue;
                    const pageIndex = Number(page.element.dataset.pageNumber) - 1;
                    if (!Number.isInteger(pageIndex) || pageIndex < 0)
                        continue;
                    const scale = pageScale(pageIndex);
                    pages.add(pageIndex);
                    rects.push({
                        page: pageIndex,
                        x: (rect.left - page.bounds.left) / scale,
                        y: (rect.top - page.bounds.top) / scale,
                        width: rect.width / scale,
                        height: rect.height / scale,
                    });
                }
            }
            const pageList = [...pages];
            const page = pageList.length ? pageList[0] : -1;
            const indices = pageList.length === 1
                ? indicesForRange(page, selection.getRangeAt(0))
                : {start: -1, end: -1};
            bridge.commit(JSON.stringify({
                text,
                pages: pageList,
                page,
                start: indices.start,
                end: indices.end,
                rects,
            }));
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
                for (const bounds of item.bounds || []) {
                    const [x, y, width, height] = bounds.map(Number);
                    if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0)
                        continue;
                    const mark = document.createElement("div");
                    mark.className = "linguaspark-annotation";
                    mark.style.left = `${x * scale}px`;
                    mark.style.top = `${y * scale}px`;
                    mark.style.width = `${width * scale}px`;
                    mark.style.height = `${height * scale}px`;
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
                if (viewer)
                    viewer.currentScale = requestedScale;
            },
            fitToWidth() {
                const viewer = application()?.pdfViewer;
                requestedScaleMode = "page-width";
                if (viewer)
                    viewer.currentScaleValue = "page-width";
            },
            clearSelection() {
                window.getSelection()?.removeAllRanges();
            },
            renderAnnotations,
        };

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
            });
            app.eventBus.on("documenterror", event => {
                bridge.failed(String(event?.message || event?.reason?.message || "PDF document failed to load"));
            });
            reportReady();
        }
        bindViewer();
    }

    function connect() {
        if (!globalThis.qt || !qt.webChannelTransport) {
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

        self._bridge = PdfJsBridge(self)
        self._bridge.selection_changed.connect(self._selection_received)
        self._bridge.empty_selection.connect(self._empty_selection)
        self._bridge.document_ready.connect(self._document_ready)
        self._bridge.current_page_changed.connect(self.current_page_changed)
        self._bridge.zoom_changed.connect(self._browser_zoom_changed)
        self._bridge.document_error.connect(self._document_error)
        self._bridge.bridge_error.connect(self.load_failed)

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
        self.stop()
        server, self._server = self._server, None
        self._ready = False
        self._path = None
        self._document_key = ""
        self._selection = None
        self._annotations = []
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
        self.set_reading_theme(self._theme_id)
        self.set_annotations(self._annotations)
        self.set_zoom_factor(self._zoom_factor)
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
