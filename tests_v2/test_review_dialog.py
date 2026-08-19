from learning_assistant.domain.models import LearningItem
from learning_assistant.ui.review_dialog import ReviewDialog


def test_new_learning_item_starts_with_meaning_recall():
    item = LearningItem(
        item_key="1",
        source_text="simple",
        query_kind="word",
        payload={"dictionary": {"translations": ["简单的"]}},
    )
    front, answer, is_cloze = ReviewDialog._card_content(item)
    assert front == "simple"
    assert "简单的" in answer
    assert is_cloze is False


def test_successful_item_uses_example_cloze():
    item = LearningItem(
        item_key="1",
        source_text="simple",
        query_kind="word",
        streak=1,
        payload={
            "dictionary": {"translations": ["简单的"]},
            "ai_note": {
                "examples": [
                    {"sentence": "Keep it simple.", "translation": "保持简单。"}
                ]
            },
        },
    )
    front, answer, is_cloze = ReviewDialog._card_content(item)
    assert front == "Keep it ____."
    assert "simple" in answer
    assert is_cloze is True
