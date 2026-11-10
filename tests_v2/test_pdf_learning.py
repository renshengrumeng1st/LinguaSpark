"""PDF vocabulary stays tied to its source and the existing review schedule."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import ReviewRating
from learning_assistant.domain.pdf_models import PdfPhrase, PdfTextSelection, PdfTranslationResult
from learning_assistant.pdf_controller import PdfTranslationController
from learning_assistant.services.pdf_text import document_key
from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.ui.review_dialog import ReviewDialog
from tests_v2.test_pdf_translation import FakePdfClient


@pytest.fixture
def learning_pdf(tmp_path):
    settings = SettingsStore(tmp_path / "settings.json", SecretStore(tmp_path / "keys.json"), tmp_path / "absent.json")
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    client = FakePdfClient()
    controller = PdfTranslationController(settings, repository, client)
    pdf = tmp_path / "reading.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    phrase = PdfPhrase("take part", "参加")
    selection = PdfTextSelection(2, 0, 29, "Take part in the discussion.")
    controller.set_selection(selection, document_key(pdf))
    # Exercise the same acceptance boundary used by a completed HTTP response.
    controller._active_request_id = 12
    controller._on_completed(12, PdfTranslationResult("参加讨论。", (phrase,)), {})
    return controller, repository, client, pdf, phrase, selection


def test_completed_pdf_phrase_persists_meaning_context_and_source(learning_pdf):
    controller, repository, client, pdf, phrase, selection = learning_pdf
    changes = []
    controller.learning_changed.connect(lambda: changes.append(True))
    assert controller.add_phrase_to_learning(phrase, str(pdf)) is True
    item, = repository.due_learning_items()
    assert item.query_kind == "word"
    assert item.source_text == "take part"
    assert item.context == selection.text
    assert item.payload["dictionary"]["translations"] == ["参加"]
    assert item.payload["ai_note"]["examples"] == [{"sentence": selection.text, "translation": "参加讨论。"}]
    assert item.payload["pdf_source"] == {
        "path": str(pdf.resolve()), "document_key": document_key(pdf),
        "page_index": 2, "selected_text": selection.text, "translation": "参加讨论。",
    }
    assert controller.is_phrase_in_learning(phrase)
    assert changes == [True]
    assert not client.start_calls


def test_repeated_add_preserves_progress_and_review_logs(learning_pdf):
    controller, repository, _, pdf, phrase, _ = learning_pdf
    controller.add_phrase_to_learning(phrase, str(pdf))
    item, = repository.due_learning_items()
    reviewed = repository.review_item(item.item_key, ReviewRating.GOOD)
    assert controller.add_phrase_to_learning(phrase, str(pdf)) is True
    restored = repository._connection().execute("SELECT * FROM learning_items WHERE item_key=?", (item.item_key,)).fetchone()
    assert restored["due_at"] == reviewed.due_at
    assert restored["streak"] == reviewed.streak
    assert repository._connection().execute("SELECT COUNT(*) FROM learning_items").fetchone()[0] == 1
    assert repository._connection().execute("SELECT COUNT(*) FROM review_logs").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["selection", "cancel", "dispose", "unreturned_phrase"])
def test_old_or_unfinished_phrases_cannot_be_saved_to_a_new_source(learning_pdf, change):
    controller, repository, _, pdf, phrase, _ = learning_pdf
    if change == "selection":
        controller.set_selection(PdfTextSelection(5, 0, 15, "Another sentence"), document_key(pdf))
    elif change == "cancel":
        controller.cancel()
    elif change == "dispose":
        controller.dispose()
    else:
        phrase = PdfPhrase("invented", "错误")
    assert controller.add_phrase_to_learning(phrase, str(pdf)) is False
    assert repository.due_learning_count() == 0


def test_ai_refresh_keeps_saved_pdf_source_and_real_example(learning_pdf):
    controller, repository, _, pdf, phrase, selection = learning_pdf
    controller.add_phrase_to_learning(phrase, str(pdf))
    original, = repository.due_learning_items()
    repository.update_learning_payload("take part", "word", {"dictionary": {"translations": ["参与"]}, "ai_note": {"examples": []}})
    refreshed, = repository.due_learning_items()
    assert refreshed.payload["pdf_source"] == original.payload["pdf_source"]
    assert refreshed.payload["ai_note"]["examples"][0]["sentence"] == selection.text
    assert refreshed.payload["dictionary"]["translations"] == ["参与"]


def test_review_keeps_pdf_sentence_even_after_ai_supplies_different_examples(learning_pdf):
    controller, repository, _, pdf, phrase, selection = learning_pdf
    controller.add_phrase_to_learning(phrase, str(pdf))
    repository.update_learning_payload("take part", "word", {
        "dictionary": {"translations": ["参加"]},
        "ai_note": {"examples": [{"sentence": "I take part every day.", "translation": "我每天都参加。"}]},
    })
    item, = repository.due_learning_items()
    item.streak = 1
    front, answer, _ = ReviewDialog._card_content(item)
    assert front == "____ in the discussion."
    assert "参加讨论。" in answer


def test_pdf_source_can_attach_to_existing_word_without_resetting_schedule(learning_pdf):
    controller, repository, _, pdf, phrase, selection = learning_pdf
    repository.toggle_learning_item("TAKE PART", "word", {"dictionary": {"translations": ["参与活动"]}}, now=100)
    item, = repository.due_learning_items(now=100)
    reviewed = repository.review_item(item.item_key, "good", now=100)
    assert controller.add_phrase_to_learning(phrase, str(pdf))
    saved, = repository.due_learning_items(now=reviewed.due_at)
    assert saved.due_at == reviewed.due_at
    assert saved.payload["dictionary"]["translations"] == ["参与活动"]
    assert saved.payload["pdf_source"]["page_index"] == 2
    assert saved.context == selection.text


class SilentSpeech:
    def speak(self, *_):
        return True


def test_review_exposes_pdf_source_and_uses_original_sentence_for_cloze(qtbot, learning_pdf):
    controller, repository, _, pdf, phrase, _ = learning_pdf
    controller.add_phrase_to_learning(phrase, str(pdf))
    dialog = ReviewDialog(repository, SilentSpeech(), controller.settings)
    qtbot.addWidget(dialog)
    dialog.reload()
    dialog.show()
    assert dialog.pdf_source_button.isVisible()
    assert "第 3 页" in dialog.pdf_source_button.text()
    requests = []
    dialog.pdf_source_requested.connect(requests.append)
    qtbot.mouseClick(dialog.pdf_source_button, Qt.LeftButton)
    assert requests[0]["path"] == str(pdf.resolve())
    assert requests[0]["page_index"] == 2
    item = dialog.current
    item.streak = 1
    front, answer, cloze = dialog._card_content(item)
    assert cloze and front == "____ in the discussion."
    assert "take part" in answer


def test_review_missing_pdf_shows_feedback_without_emitting_navigation(qtbot, learning_pdf):
    controller, repository, _, pdf, phrase, _ = learning_pdf
    controller.add_phrase_to_learning(phrase, str(pdf))
    pdf.unlink()
    dialog = ReviewDialog(repository, SilentSpeech(), controller.settings)
    qtbot.addWidget(dialog)
    dialog.reload()
    requests = []
    dialog.pdf_source_requested.connect(requests.append)
    dialog.pdf_source_button.click()
    assert not requests
    assert "移动或删除" in dialog.hint.text()
