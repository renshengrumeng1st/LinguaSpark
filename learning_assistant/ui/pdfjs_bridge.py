"""Validated WebChannel boundary for PDF.js text selections."""

from __future__ import annotations

import json
import math

from PySide6.QtCore import QObject, Signal, Slot

from learning_assistant.domain.pdf_models import PdfTextSelection
from learning_assistant.services.pdf_text import normalize_pdf_selection


class PdfJsBridge(QObject):
    """Convert untrusted browser payloads into the reader domain model."""

    selection_changed = Signal(object)
    empty_selection = Signal(bool)
    document_ready = Signal(int)
    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    document_error = Signal(str)
    bridge_error = Signal(str)

    @Slot(int)
    def ready(self, page_count: int) -> None:
        self.document_ready.emit(max(0, int(page_count)))

    @Slot(int)
    def page_changed(self, page_index: int) -> None:
        self.current_page_changed.emit(max(0, int(page_index)))

    @Slot(float)
    def scale_changed(self, factor: float) -> None:
        value = float(factor)
        if math.isfinite(value) and value > 0:
            self.zoom_changed.emit(value)

    @Slot(str)
    def failed(self, message: str) -> None:
        self.document_error.emit(str(message or ""))

    @Slot(bool)
    def empty(self, has_selectable_text: bool) -> None:
        self.empty_selection.emit(bool(has_selectable_text))

    @Slot(str)
    def commit(self, raw_payload: str) -> None:
        try:
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise TypeError("selection payload must be an object")
            raw_text = str(payload.get("text", ""))
            if not raw_text.strip():
                self.selection_changed.emit(None)
                return
            text = normalize_pdf_selection(raw_text)
            pages = tuple(dict.fromkeys(int(page) for page in payload.get("pages", ())))
            if not pages or any(page < 0 for page in pages):
                raise ValueError("selection has no valid page")
            page_index = int(payload.get("page", pages[0]))
            if page_index not in pages:
                raise ValueError("selection page is inconsistent")
            start_index = int(payload.get("start", -1))
            end_index = int(payload.get("end", -1))
            if start_index > end_index:
                start_index, end_index = end_index, start_index
            stable_indices = start_index >= 0 and end_index > start_index
            bounds = tuple(
                rect[1:]
                for rect in (self._rect(item) for item in payload.get("rects", ()))
                if rect[0] == page_index
            )
            can_annotate = len(pages) == 1 and stable_indices and bool(bounds)
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.bridge_error.emit(f"invalid PDF.js selection payload: {error}")
            return
        self.selection_changed.emit(
            PdfTextSelection(
                page_index=page_index,
                start_index=start_index,
                end_index=end_index,
                text=text,
                bounds=bounds,
                can_annotate=can_annotate,
            )
        )

    @staticmethod
    def _rect(item: object) -> tuple[int, float, float, float, float]:
        if not isinstance(item, dict):
            raise TypeError("selection rectangle must be an object")
        page = int(item["page"])
        values = (
            float(item["x"]),
            float(item["y"]),
            float(item["width"]),
            float(item["height"]),
        )
        if page < 0 or not all(math.isfinite(value) for value in values):
            raise ValueError("selection rectangle contains invalid values")
        if values[2] <= 0 or values[3] <= 0:
            raise ValueError("selection rectangle must have positive size")
        return (page, *values)
