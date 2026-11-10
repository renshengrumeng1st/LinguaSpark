import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.library_dialog import LibraryDialog
from tests_v2.test_convenience import experience  # noqa: F401 - temporary application fixture


def test_typing_preview_does_not_save_prefix_history(qtbot, experience):
    window, _, ai, repo, _ = experience
    window.input.setPlainText("abu")
    qtbot.waitUntil(lambda: window.word_view.word.text() == "abu")
    assert repo.saved_items() == []
    window.input.setPlainText("abundance")
    qtbot.waitUntil(lambda: len(ai.calls) == 1)
    ai.completed.emit(1, {"plain_explanation": "丰富"}, {})
    assert [row["source_text"] for row in repo.saved_items()] == ["abundance"]


def test_manual_local_query_still_saves_history(experience):
    window, _, ai, repo, settings = experience
    settings.set("models", [])
    window.input.setPlainText("abundance")
    window.submit()
    assert not ai.calls
    assert [row["source_text"] for row in repo.saved_items()] == ["abundance"]


def test_failed_manual_ai_query_keeps_the_requested_word(experience):
    window, _, ai, repo, _ = experience
    window.input.setPlainText("abundance")
    window.submit()
    ai.failed.emit(1, "暂时不可用", {})
    assert [row["source_text"] for row in repo.saved_items()] == ["abundance"]


@pytest.fixture
def library(qtbot, tmp_path):
    repo = LearningRepository(tmp_path / "learning.sqlite3")
    for text in ("abu", "abundance", "hello"):
        repo.add_history(text, "word", {"dictionary": {"word": text}}, "en", "zh-CN")
    repo.toggle_favorite("abu", "word", {})
    repo.toggle_learning_item("abu", "word", {})
    dialog = LibraryDialog(repo)
    qtbot.addWidget(dialog)
    dialog.show()
    yield dialog, repo
    dialog._search_timer.stop()
    repo._connection().close()


def test_batch_delete_only_checked_history_and_preserves_other_data(qtbot, library, monkeypatch):
    dialog, repo = library
    qtbot.mouseClick(dialog.batch_button, Qt.LeftButton)
    dialog.item_list.item(0).setCheckState(Qt.Checked)
    dialog.item_list.item(2).setCheckState(Qt.Checked)
    kept = dialog.item_list.item(1).data(Qt.UserRole)["identifier"]
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda parent, title, message, *args: prompts.append(message) or QMessageBox.Yes)
    qtbot.mouseClick(dialog.bulk_delete_button, Qt.LeftButton)
    assert len(repo.saved_items()) == 1
    assert repo.saved_items()[0]["identifier"] == kept
    assert prompts and "2" in prompts[0]
    assert repo.is_favorite("abu", "word")
    assert repo.is_learning_item("abu", "word")


def test_cancelling_batch_confirmation_keeps_records_and_checks(qtbot, library, monkeypatch):
    dialog, repo = library
    qtbot.mouseClick(dialog.batch_button, Qt.LeftButton)
    qtbot.mouseClick(dialog.select_all_button, Qt.LeftButton)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    qtbot.mouseClick(dialog.bulk_delete_button, Qt.LeftButton)
    assert len(repo.saved_items()) == 3
    assert all(dialog.item_list.item(i).checkState() == Qt.Checked for i in range(3))


def test_filter_resets_checks_and_batch_is_not_available_for_favorites(qtbot, library):
    dialog, repo = library
    qtbot.mouseClick(dialog.batch_button, Qt.LeftButton)
    qtbot.mouseClick(dialog.select_all_button, Qt.LeftButton)
    dialog.search.setText("abundance")
    assert not dialog.bulk_delete_button.isEnabled()
    qtbot.waitUntil(lambda: dialog.item_list.count() == 1)
    assert dialog.item_list.item(0).checkState() == Qt.Unchecked
    assert not dialog.bulk_delete_button.isEnabled()
    dialog.tabs.setCurrentIndex(1)
    assert not dialog.batch_button.isVisible()
    assert not dialog.bulk_delete_button.isVisible()


def test_select_all_only_marks_loaded_rows(qtbot, library):
    dialog, repo = library
    for index in range(105):
        repo.add_history(f"word{index}", "word", {}, "en", "zh-CN")
    dialog.reload()
    qtbot.mouseClick(dialog.batch_button, Qt.LeftButton)
    qtbot.mouseClick(dialog.select_all_button, Qt.LeftButton)
    assert dialog.item_list.count() == 100
    assert "100" in dialog.bulk_delete_button.text()
    dialog._append()
    assert dialog.item_list.count() == 108
    assert sum(dialog.item_list.item(i).checkState() == Qt.Checked for i in range(108)) == 100


def test_bulk_history_delete_is_atomic(library):
    _, repo = library
    identifiers = [row["identifier"] for row in repo.saved_items()]
    repo._connection().execute(f"CREATE TRIGGER protect_history BEFORE DELETE ON query_history WHEN OLD.id = {int(identifiers[1])} BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    repo._connection().commit()
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_history(identifiers)
    assert len(repo.saved_items()) == 3
