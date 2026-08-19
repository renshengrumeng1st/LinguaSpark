from pathlib import Path

from learning_assistant.storage.learning_repository import LearningRepository
from learning_assistant.domain.models import ReviewRating


def test_cache_and_favorite_roundtrip(tmp_path: Path):
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    key = repository.stable_key("model", "hello")
    repository.put_ai_cache(key, {"plain_explanation": "问候"})
    assert repository.get_ai_cache(key) == {"plain_explanation": "问候"}
    assert repository.toggle_favorite("hello", "word", {"meaning": "你好"}) is True
    assert repository.is_favorite("HELLO", "word") is True
    assert repository.toggle_favorite("hello", "word", {}) is False


def test_learning_queue_and_review_schedule(tmp_path: Path):
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    payload = {
        "dictionary": {"translations": ["你好"]},
        "ai_note": {"examples": [{"sentence": "Hello, Sam.", "translation": "你好，山姆。"}]},
    }
    assert repository.toggle_learning_item("hello", "word", payload, now=1_000) is True
    assert repository.is_learning_item("HELLO", "word") is True
    items = repository.due_learning_items(now=1_000)
    assert len(items) == 1
    assert items[0].payload == payload

    again = repository.review_item(items[0].item_key, ReviewRating.AGAIN, now=1_000)
    assert again.due_at == 1_600
    assert again.lapses == 1
    assert repository.due_learning_count(now=1_599) == 0

    good = repository.review_item(items[0].item_key, ReviewRating.GOOD, now=1_600)
    assert good.interval_days == 3
    assert good.due_at == 1_600 + 3 * 86_400


def test_hard_review_uses_gradual_interval(tmp_path: Path):
    repository = LearningRepository(tmp_path / "learning.sqlite3")
    repository.toggle_learning_item("study", "word", {}, now=100)
    item = repository.due_learning_items(now=100)[0]
    hard = repository.review_item(item.item_key, "hard", now=100)
    assert hard.interval_days == 1
