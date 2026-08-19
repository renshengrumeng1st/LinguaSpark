"""Language-neutral value objects used by the PDF reading workflow."""

from __future__ import annotations

from dataclasses import dataclass


PdfBounds = tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True, slots=True)
class PdfPhrase:
    source: str
    meaning: str


@dataclass(frozen=True, slots=True)
class PdfTranslationResult:
    translation: str
    phrases: tuple[PdfPhrase, ...] = ()


@dataclass(frozen=True, slots=True)
class PdfStreamUpdate:
    translation_delta: str = ""
    phrases: tuple[PdfPhrase, ...] = ()


@dataclass(frozen=True, slots=True)
class PdfTextSelection:
    page_index: int
    start_index: int
    end_index: int
    text: str
    bounds: PdfBounds = ()
