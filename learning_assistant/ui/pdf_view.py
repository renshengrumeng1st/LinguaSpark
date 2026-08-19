"""Continuous Qt PDF view with local text selection and highlight overlays."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMargins, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from learning_assistant.domain.pdf_models import PdfAnnotation, PdfTextSelection
from learning_assistant.services.pdf_text import document_key, normalize_pdf_selection


READING_THEMES = {
    "eye_care": "#EAF4E2",
    "paper": "#F7F1E3",
    "soft_gray": "#EEF1F4",
    "white": "#FFFFFF",
}

HIGHLIGHT_COLORS = {
    "yellow": QColor(250, 204, 21, 105),
    "green": QColor(74, 222, 128, 95),
    "pink": QColor(244, 114, 182, 95),
}


@dataclass(frozen=True, slots=True)
class _PageRect:
    index: int
    rect: QRectF


class PdfPageLayout:
    """Pure geometry shared by hit testing and overlay painting."""

    def __init__(
        self,
        page_sizes: list[tuple[float, float]],
        zoom: float,
        viewport_width: float,
        margin: float,
        spacing: float,
    ):
        self.zoom = max(0.01, float(zoom))
        self.margin = max(0.0, float(margin))
        self.spacing = max(0.0, float(spacing))
        scaled = [
            (max(0.0, width) * self.zoom, max(0.0, height) * self.zoom)
            for width, height in page_sizes
        ]
        widest = max((width for width, _ in scaled), default=0.0)
        self.content_width = max(float(viewport_width), widest + 2 * self.margin)
        top = self.margin
        pages: list[_PageRect] = []
        for index, (width, height) in enumerate(scaled):
            left = (self.content_width - width) / 2
            pages.append(_PageRect(index, QRectF(left, top, width, height)))
            top += height + self.spacing
        self.pages = tuple(pages)
        self.content_height = (
            top - self.spacing + self.margin if pages else 0.0
        )

    def hit_test(
        self,
        viewport_x: float,
        viewport_y: float,
        scroll_y: float,
        scroll_x: float = 0.0,
    ) -> tuple[int, QPointF] | None:
        content = QPointF(viewport_x + scroll_x, viewport_y + scroll_y)
        for page in self.pages:
            if page.rect.contains(content):
                relative = content - page.rect.topLeft()
                return page.index, QPointF(
                    relative.x() / self.zoom,
                    relative.y() / self.zoom,
                )
        return None

    def pdf_rect_to_viewport(
        self,
        page_index: int,
        bounds: tuple[float, float, float, float],
        scroll_y: float,
        scroll_x: float = 0.0,
    ) -> QRectF:
        page = next((item for item in self.pages if item.index == page_index), None)
        if page is None:
            return QRectF()
        x, y, width, height = bounds
        return QRectF(
            page.rect.left() + x * self.zoom - scroll_x,
            page.rect.top() + y * self.zoom - scroll_y,
            width * self.zoom,
            height * self.zoom,
        )


class SelectablePdfView(QPdfView):
    selection_changed = Signal(object)
    document_loaded = Signal(str, int)
    load_failed = Signal(str)
    current_page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document = QPdfDocument(self)
        self.setDocument(self._document)
        self.setPageMode(QPdfView.PageMode.MultiPage)
        self.setZoomMode(QPdfView.ZoomMode.Custom)
        self.setZoomFactor(1.0)
        self.setDocumentMargins(QMargins(24, 24, 24, 24))
        self.setPageSpacing(16)
        self._path: Path | None = None
        self._document_key = ""
        self._selection: PdfTextSelection | None = None
        self._annotations: list[PdfAnnotation] = []
        self._drag_start: tuple[int, QPointF] | None = None
        self._drag_end: tuple[int, QPointF] | None = None
        self._theme_id = "eye_care"
        self._current_page = -1
        self.verticalScrollBar().valueChanged.connect(self._update_current_page)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)

    @property
    def document_key(self) -> str:
        return self._document_key

    def current_selection(self) -> PdfTextSelection | None:
        return self._selection

    def load_file(self, path: str | Path) -> bool:
        candidate = Path(path).resolve()
        self._selection = None
        self._annotations = []
        self._path = candidate
        self._document_key = ""
        self._document.close()
        error = self._document.load(str(candidate))
        if error != QPdfDocument.Error.None_:
            message = (
                "此 PDF 需要密码"
                if error == QPdfDocument.Error.IncorrectPassword
                else "无法打开此 PDF"
            )
            self.load_failed.emit(message)
            return False
        self._document_key = document_key(self._path)
        self.document_loaded.emit(self._document_key, self._document.pageCount())
        self._update_current_page()
        return True

    def set_pdf_password(self, password: str) -> bool:
        if not self._path:
            return False
        self._document.setPassword(password)
        return self.load_file(self._path)

    def set_annotations(self, annotations: list[PdfAnnotation]) -> None:
        self._annotations = list(annotations)
        self.viewport().update()

    def set_reading_theme(self, theme_id: str) -> None:
        self._theme_id = theme_id if theme_id in READING_THEMES else "eye_care"
        self.viewport().update()

    def set_zoom_factor(self, value: float) -> None:
        self.setZoomMode(QPdfView.ZoomMode.Custom)
        self.setZoomFactor(max(0.5, min(3.0, float(value))))
        self._update_current_page()

    def _layout(self) -> PdfPageLayout:
        sizes = [
            (
                self._document.pagePointSize(index).width(),
                self._document.pagePointSize(index).height(),
            )
            for index in range(self._document.pageCount())
        ]
        margins = self.documentMargins()
        return PdfPageLayout(
            sizes,
            self.zoomFactor(),
            self.viewport().width(),
            float(max(margins.left(), margins.right())),
            float(self.pageSpacing()),
        )

    def _hit(self, position: QPointF) -> tuple[int, QPointF] | None:
        return self._layout().hit_test(
            position.x(),
            position.y(),
            self.verticalScrollBar().value(),
            self.horizontalScrollBar().value(),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self._hit(event.position())
            self._drag_end = self._drag_start
            self._selection = None
            self.viewport().update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start and event.buttons() & Qt.MouseButton.LeftButton:
            hit = self._hit(event.position())
            if hit and hit[0] == self._drag_start[0]:
                self._drag_end = hit
                self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_start:
            super().mouseReleaseEvent(event)
            return
        hit = self._hit(event.position())
        if hit and hit[0] == self._drag_start[0]:
            self._drag_end = hit
        start = self._drag_start
        end = self._drag_end
        self._drag_start = None
        self._drag_end = None
        if not end or start[0] != end[0]:
            self.selection_changed.emit(None)
            return
        selected = self._document.getSelection(start[0], start[1], end[1])
        if not selected.isValid():
            self.selection_changed.emit(None)
            return
        try:
            text = normalize_pdf_selection(selected.text())
        except ValueError as exc:
            self.load_failed.emit(str(exc))
            return
        if not text:
            self.selection_changed.emit(None)
            return
        bounds: list[tuple[float, float, float, float]] = []
        for polygon in selected.bounds():
            rect = polygon.boundingRect()
            bounds.append((rect.x(), rect.y(), rect.width(), rect.height()))
        start_index, end_index = selected.startIndex(), selected.endIndex()
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        self._selection = PdfTextSelection(
            start[0], start_index, end_index, text, tuple(bounds)
        )
        self.selection_changed.emit(self._selection)
        self.viewport().update()
        event.accept()

    def _update_current_page(self, *_args) -> None:
        if not self._document.pageCount():
            return
        center = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        hit = self._hit(center)
        if hit and hit[0] != self._current_page:
            self._current_page = hit[0]
            self.current_page_changed.emit(self._current_page)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_current_page()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._document.pageCount():
            return
        painter = QPainter(self.viewport())
        layout = self._layout()
        scroll_y = self.verticalScrollBar().value()
        scroll_x = self.horizontalScrollBar().value()
        viewport_rect = QRectF(self.viewport().rect())

        theme = QColor(READING_THEMES[self._theme_id])
        theme.setAlpha(42 if self._theme_id != "white" else 0)
        if theme.alpha():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme)
            for page in layout.pages:
                rect = page.rect.translated(-scroll_x, -scroll_y)
                if rect.intersects(viewport_rect):
                    painter.drawRect(rect)

        painter.setPen(Qt.PenStyle.NoPen)
        for annotation in self._annotations:
            painter.setBrush(HIGHLIGHT_COLORS.get(annotation.color, QColor()))
            for bound in annotation.bounds:
                painter.drawRect(layout.pdf_rect_to_viewport(
                    annotation.page_index, bound, scroll_y, scroll_x
                ))
        if self._selection:
            painter.setBrush(QColor(59, 130, 246, 88))
            for bound in self._selection.bounds:
                painter.drawRect(layout.pdf_rect_to_viewport(
                    self._selection.page_index, bound, scroll_y, scroll_x
                ))
        painter.end()
