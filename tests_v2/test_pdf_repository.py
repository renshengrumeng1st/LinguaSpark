from __future__ import annotations

from pathlib import Path

import pytest

from learning_assistant.domain.pdf_models import PdfTextSelection
from learning_assistant.storage.learning_repository import LearningRepository


def _selection(page: int = 2, start: int = 10, end: int = 24) -> PdfTextSelection:
    return PdfTextSelection(
        page_index=page,
        start_index=start,
        end_index=end,
        text="selected phrase",
        bounds=((1.0, 2.0, 30.0, 8.0),),
    )


def test_pdf_annotation_round_trip_and_color_update(tmp_path: Path) -> None:
    repo = LearningRepository(tmp_path / "learning.sqlite3")

    first = repo.add_pdf_annotation("doc", _selection(), "yellow", now=100)
    updated = repo.add_pdf_annotation("doc", _selection(), "green", now=101)
    saved = repo.pdf_annotations("doc", page_index=2)

    assert first.id == updated.id
    assert len(saved) == 1
    assert saved[0].color == "green"
    assert saved[0].selected_text == "selected phrase"
    assert saved[0].bounds == ((1.0, 2.0, 30.0, 8.0),)
    assert saved[0].created_at == 101


def test_pdf_annotations_are_isolated_and_filterable_by_page(tmp_path: Path) -> None:
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    repo.add_pdf_annotation("first", _selection(page=0), "yellow", now=1)
    repo.add_pdf_annotation("first", _selection(page=1), "pink", now=2)
    repo.add_pdf_annotation("second", _selection(page=0), "green", now=3)

    assert [item.page_index for item in repo.pdf_annotations("first")] == [0, 1]
    assert [item.color for item in repo.pdf_annotations("first", page_index=1)] == [
        "pink"
    ]
    assert [item.color for item in repo.pdf_annotations("second")] == ["green"]


def test_pdf_annotation_rejects_unknown_color(tmp_path: Path) -> None:
    repo = LearningRepository(tmp_path / "learning.sqlite3")

    with pytest.raises(ValueError, match="yellow, green, pink"):
        repo.add_pdf_annotation("doc", _selection(), "blue")

    assert repo.pdf_annotations("doc") == []


def test_delete_pdf_annotation_reports_whether_a_row_was_removed(tmp_path: Path) -> None:
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    repo.add_pdf_annotation("doc", _selection(), "yellow")

    assert repo.delete_pdf_annotation("doc", 2, 10, 24) is True
    assert repo.delete_pdf_annotation("doc", 2, 10, 24) is False
    assert repo.pdf_annotations("doc") == []
