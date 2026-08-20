"""Fast, UI-independent helpers for selected PDF text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from learning_assistant.domain.pdf_models import (
    PdfPhrase,
    PdfStreamUpdate,
    PdfTranslationResult,
)


PHRASE_DELIMITER = "<<<PHRASES>>>"


def normalize_pdf_selection(text: str, max_length: int = 4000) -> str:
    """Normalize PDF line layout without sending unrelated page content."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_length:
        raise ValueError(f"选中文本不能超过 {max_length:,} 个字符")
    return value


def document_key(path: Path) -> str:
    """Return a cheap identity that changes when this local file changes."""
    resolved = Path(path).resolve()
    info = resolved.stat()
    material = json.dumps(
        [str(resolved).casefold(), info.st_size, info.st_mtime_ns],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class PdfTranslationStreamParser:
    """Split streamed model output into immediate translation and later phrases."""

    def __init__(self, max_phrases: int = 5):
        self.max_phrases = max(0, int(max_phrases))
        self._translation_pending = ""
        self._translation_parts: list[str] = []
        self._phrase_pending = ""
        self._phrases: list[PdfPhrase] = []
        self._phrase_sources: set[str] = set()
        self._in_phrases = False

    @staticmethod
    def _delimiter_prefix_length(value: str) -> int:
        limit = min(len(value), len(PHRASE_DELIMITER) - 1)
        for length in range(limit, 0, -1):
            if PHRASE_DELIMITER.startswith(value[-length:]):
                return length
        return 0

    def _parse_phrase_line(self, line: str) -> PdfPhrase | None:
        if len(self._phrases) >= self.max_phrases or "||" not in line:
            return None
        source, meaning = (part.strip() for part in line.split("||", 1))
        identity = source.casefold()
        if not source or not meaning or identity in self._phrase_sources:
            return None
        phrase = PdfPhrase(source, meaning)
        self._phrases.append(phrase)
        self._phrase_sources.add(identity)
        return phrase

    def _consume_complete_phrase_lines(self) -> tuple[PdfPhrase, ...]:
        added: list[PdfPhrase] = []
        while "\n" in self._phrase_pending:
            line, self._phrase_pending = self._phrase_pending.split("\n", 1)
            phrase = self._parse_phrase_line(line.rstrip("\r"))
            if phrase is not None:
                added.append(phrase)
        return tuple(added)

    def feed(self, chunk: str) -> PdfStreamUpdate:
        value = str(chunk or "")
        if not value:
            return PdfStreamUpdate()
        if self._in_phrases:
            self._phrase_pending += value
            return PdfStreamUpdate(phrases=self._consume_complete_phrase_lines())

        self._translation_pending += value
        marker_index = self._translation_pending.find(PHRASE_DELIMITER)
        if marker_index >= 0:
            translation = self._translation_pending[:marker_index]
            self._translation_parts.append(translation)
            self._phrase_pending = self._translation_pending[
                marker_index + len(PHRASE_DELIMITER):
            ]
            self._translation_pending = ""
            self._in_phrases = True
            return PdfStreamUpdate(
                translation_delta=translation,
                phrases=self._consume_complete_phrase_lines(),
            )

        held = self._delimiter_prefix_length(self._translation_pending)
        emitted = self._translation_pending[:-held] if held else self._translation_pending
        self._translation_pending = self._translation_pending[-held:] if held else ""
        self._translation_parts.append(emitted)
        return PdfStreamUpdate(translation_delta=emitted)

    def close(self) -> PdfTranslationResult:
        if self._in_phrases:
            if self._phrase_pending:
                self._parse_phrase_line(self._phrase_pending.rstrip("\r"))
                self._phrase_pending = ""
        elif self._translation_pending:
            self._translation_parts.append(self._translation_pending)
            self._translation_pending = ""
        return PdfTranslationResult(
            translation="".join(self._translation_parts).strip(),
            phrases=tuple(self._phrases),
        )
