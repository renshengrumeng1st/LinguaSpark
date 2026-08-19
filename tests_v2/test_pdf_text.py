from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


def _pdf_modules():
    assert importlib.util.find_spec("learning_assistant.domain.pdf_models") is not None, (
        "PDF domain models are missing"
    )
    assert importlib.util.find_spec("learning_assistant.services.pdf_text") is not None, (
        "PDF text services are missing"
    )
    return (
        importlib.import_module("learning_assistant.domain.pdf_models"),
        importlib.import_module("learning_assistant.services.pdf_text"),
    )


def test_normalize_pdf_selection_joins_hyphenated_line_breaks() -> None:
    _, pdf_text = _pdf_modules()

    assert pdf_text.normalize_pdf_selection(
        "A trans-\r\nlation  test.\nNext"
    ) == "A translation test. Next"


def test_normalize_pdf_selection_rejects_oversized_text() -> None:
    _, pdf_text = _pdf_modules()

    assert pdf_text.normalize_pdf_selection(" \n\t ") == ""
    with pytest.raises(ValueError, match="4,000"):
        pdf_text.normalize_pdf_selection("x" * 4001)


def test_document_key_changes_when_the_file_identity_changes(tmp_path: Path) -> None:
    _, pdf_text = _pdf_modules()
    document = tmp_path / "paper.pdf"
    document.write_bytes(b"first")

    first = pdf_text.document_key(document)
    assert first == pdf_text.document_key(document)
    document.write_bytes(b"second-version")

    assert pdf_text.document_key(document) != first


def test_stream_parser_handles_delimiter_split_between_chunks() -> None:
    models, pdf_text = _pdf_modules()
    parser = pdf_text.PdfTranslationStreamParser()

    first = parser.feed("自然译文<<<PHRA")
    second = parser.feed("SES>>>\ntake part || 参加\nin context || 在语境中\n")
    result = parser.close()

    assert first.translation_delta == "自然译文"
    assert first.phrases == ()
    assert second.phrases == (
        models.PdfPhrase("take part", "参加"),
        models.PdfPhrase("in context", "在语境中"),
    )
    assert result == models.PdfTranslationResult(
        "自然译文",
        (
            models.PdfPhrase("take part", "参加"),
            models.PdfPhrase("in context", "在语境中"),
        ),
    )


def test_stream_parser_without_delimiter_keeps_all_text_as_translation() -> None:
    models, pdf_text = _pdf_modules()
    parser = pdf_text.PdfTranslationStreamParser()

    first = parser.feed("只有译")
    second = parser.feed("文")
    result = parser.close()

    assert first.translation_delta + second.translation_delta == "只有译文"
    assert result == models.PdfTranslationResult("只有译文", ())


def test_stream_parser_deduplicates_and_caps_phrase_analysis() -> None:
    models, pdf_text = _pdf_modules()
    parser = pdf_text.PdfTranslationStreamParser()
    lines = [
        "one || 一",
        "two || 二",
        "one || 重复",
        "malformed line",
        "three || 三",
        "four || 四",
        "five || 五",
        "six || 六",
        " || 空",
    ]

    update = parser.feed("译文<<<PHRASES>>>\n" + "\n".join(lines) + "\n")

    assert update.phrases == tuple(
        models.PdfPhrase(source, meaning)
        for source, meaning in (
            ("one", "一"),
            ("two", "二"),
            ("three", "三"),
            ("four", "四"),
            ("five", "五"),
        )
    )
    assert parser.close().phrases == update.phrases
