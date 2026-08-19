from learning_assistant.domain.models import AiStudyNote, SentenceResult


def test_ai_note_normalizes_provider_output():
    note = AiStudyNote.from_dict({
        "plain_explanation": "  easy explanation ",
        "synonyms": "simple",
        "collocations": ["make progress", ""],
        "examples": [{"sentence": "I made progress.", "translation": "我取得了进步。"}],
    })
    assert note.plain_explanation == "easy explanation"
    assert note.synonyms == ["simple"]
    assert note.collocations == ["make progress"]
    assert note.examples[0]["sentence"] == "I made progress."


def test_sentence_result_ignores_invalid_phrases():
    result = SentenceResult.from_dict({
        "translation": "你好",
        "key_phrases": [{"phrase": "say hello", "meaning": "问好"}, "bad"],
        "learning_tip": "简短提示",
    })
    assert result.translation == "你好"
    assert result.key_phrases == [{"phrase": "say hello", "meaning": "问好"}]

