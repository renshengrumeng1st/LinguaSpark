"""Offline TeX-to-SVG conversion for the native PDF answer browser."""

from collections import OrderedDict
from html import escape
import hashlib
import json
import math
import re

from PySide6.QtCore import QByteArray, QEvent, QObject, QUrl, QTimer, Signal, Qt
from PySide6.QtGui import QFontMetricsF, QImage, QPainter, QTextDocument
from PySide6.QtSvg import QSvgRenderer

from learning_assistant.core.paths import project_root
from learning_assistant.ui.pdf_markdown import render_markdown


MATH_ASSET = project_root() / "assets" / "mathjax-3.2.2" / "tex-svg.js"
MATH_PATTERN = re.compile(r"\\\[(.*?)\\\]|\\\((.*?)\\\)|\$\$(.*?)\$\$|(?<!\\)\$(?!\$)([^\n$]+?)\$(?!\$)", re.DOTALL)


class PdfMathRenderer(QObject):
    ready = Signal()

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        self._cache = OrderedDict()
        self._queue = OrderedDict()
        self._images = OrderedDict()
        self._page = None
        self._profile = None
        self._ready = False
        self._busy = False
        self._active_key = None
        self._failed = False
        self._disposed = False
        self._polls = 0
        self._render_width = self.browser.viewport().width()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._viewport_resized)
        self.browser.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self._cache and not self._disposed:
            # setHtml temporarily removes/re-adds the scrollbar. Inspect the
            # settled width after layout, rather than feeding a render loop.
            self._resize_timer.start(0)
        return super().eventFilter(watched, event)

    def _viewport_resized(self):
        width = self.browser.viewport().width()
        if not self._disposed and width != self._render_width:
            self._render_width = width
            self.ready.emit()

    @property
    def pending(self):
        return bool(self._queue) or self._busy

    def _start(self):
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor

        class LocalOnly(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                url = info.requestUrl()
                allowed = url.scheme() in {"data", "about"} or url == QUrl.fromLocalFile(str(MATH_ASSET.resolve()))
                info.block(not allowed)

        self._profile = QWebEngineProfile(self)
        self._interceptor = LocalOnly(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self._page = QWebEnginePage(self._profile, self)
        self._page.loadFinished.connect(self._loaded)
        self._page.renderProcessTerminated.connect(lambda *_: self._fail())
        html = """<!doctype html><html><head><meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src file: 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'">
        <script>window.MathJax={loader:{load:[]},tex:{packages:['base','ams'],maxMacros:500,maxBuffer:4000},
        svg:{fontCache:'none'},startup:{typeset:false}};</script>
        <script src="tex-svg.js"></script><script>
        MathJax.startup.promise.then(()=>{window.mathReady=true;});
        </script></head><body></body></html>"""
        self._page.setHtml(html, QUrl.fromLocalFile(str(MATH_ASSET.parent.resolve() / "index.html")))

    def _loaded(self, success):
        if not success:
            self._fail()
        else:
            self._poll()

    def _poll(self):
        if self._disposed or self._failed:
            return
        self._page.runJavaScript("Boolean(window.mathReady)", self._polled)

    def _polled(self, ready):
        if self._disposed:
            return
        if ready:
            self._ready = True
            self._process()
        elif self._polls < 100:
            self._polls += 1
            QTimer.singleShot(50, self, self._poll)
        else:
            self._fail()

    def _fail(self):
        self._failed = True
        self._busy = False
        self._queue.clear()
        if not self._disposed:
            self.ready.emit()

    def _process(self):
        if self._disposed or not self._ready or self._busy or not self._queue:
            return
        key, _ = self._queue.popitem(last=False)
        expression, display = key
        self._busy = True
        self._active_key = key
        script = "window.mathResult={done:false}; MathJax.tex2svgPromise(" + json.dumps(expression) + ", {display:" + json.dumps(display) + "}).then(node => {" + """
            const svg = node.querySelector('svg');
            const value = !svg || node.querySelector('[data-mml-node="merror"]') ? null :
                {svg:svg.outerHTML.replaceAll('currentColor','#1f2937'),
                 width:parseFloat(svg.getAttribute('width')),height:parseFloat(svg.getAttribute('height'))};
            window.mathResult={done:true,value};
        }).catch(() => {window.mathResult={done:true,value:null};});"""
        self._page.runJavaScript(script, lambda _: self._poll_result(key, 0))

    def _poll_result(self, key, attempts):
        if self._disposed or self._failed:
            return
        def received(result):
            if self._disposed:
                return
            try:
                result = json.loads(result) if isinstance(result, str) else None
            except ValueError:
                result = None
            if isinstance(result, dict) and result.get("done"):
                self._converted(key, result.get("value"))
            elif attempts < 150:
                QTimer.singleShot(30, self, lambda: self._poll_result(key, attempts + 1))
            else:
                self._converted(key, None)
        self._page.runJavaScript("JSON.stringify(window.mathResult)", received)

    def _converted(self, key, result):
        if self._disposed:
            return
        self._busy = False
        self._active_key = None
        self._cache[key] = result if isinstance(result, dict) and result.get("svg") else None
        self.ready.emit()
        self._process()

    def format(self, text, replacements=()):
        self._render_width = self.browser.viewport().width()
        protected = list(replacements)
        for match in MATH_PATTERN.finditer(text):
            if any(start < match.end() and stop > match.start() for start, stop, _ in replacements):
                continue
            protected.append((match.start(), match.end(), lambda value=match: self._format_math(value)))
        return render_markdown(text, protected)

    def _format_math(self, match):
        expression = next(group for group in match.groups() if group is not None)
        display = match.group(1) is not None or match.group(3) is not None
        key = (expression, display)
        rendered = None
        if 0 < len(expression) <= 2000 and not self._failed and not self._disposed:
            if key in self._cache:
                rendered = self._image(key, self._cache[key], match.group(0))
            elif key != self._active_key and len(self._cache) + len(self._queue) < 128:
                self._queue[key] = None
                if self._page is None:
                    self._start()
                self._process()
        return rendered or escape(match.group(0))

    def _image(self, key, result, source):
        if not result:
            return None
        x_height = QFontMetricsF(self.browser.font()).xHeight()
        width, height = result["width"] * x_height, result["height"] * x_height
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            return None
        ratio = min(1, max(40, self.browser.viewport().width() - 24) / width, 800 / height)
        width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
        dpr = self.browser.devicePixelRatioF()
        image_key = (key, width, height, dpr)
        url = QUrl("pdf-math:" + hashlib.sha256(repr(image_key).encode()).hexdigest())
        if image_key not in self._images:
            renderer = QSvgRenderer(QByteArray(result["svg"].encode()))
            if not renderer.isValid():
                return None
            image = QImage(math.ceil(width * dpr), math.ceil(height * dpr), QImage.Format_ARGB32_Premultiplied)
            if image.isNull():
                return None
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            image.setDevicePixelRatio(dpr)
            self._images[image_key] = image
            while len(self._images) > 128:
                self._images.popitem(last=False)
        self.browser.document().addResource(QTextDocument.ImageResource, url, self._images[image_key])
        tag = f'<img src="{url.toString()}" width="{width}" height="{height}" alt="{escape(source, quote=True)}" align="middle">'
        return "<br>" + tag + "<br>" if key[1] else tag

    def dispose(self):
        self._disposed = True
        self._resize_timer.stop()
        self._queue.clear()
        if self._page is not None:
            self._page.deleteLater()
            self._profile.deleteLater()
