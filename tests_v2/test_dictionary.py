import csv
from pathlib import Path

from learning_assistant.services.dictionary import DictionaryRepository
from tools.build_dictionary import build


def test_dictionary_build_and_inflection_lookup(tmp_path: Path):
    source = tmp_path / "ecdict.csv"
    fields = [
        "word", "phonetic", "definition", "translation", "pos", "collins",
        "oxford", "tag", "bnc", "frq", "exchange", "detail", "audio",
    ]
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "word": "study", "phonetic": "ˈstʌdi", "definition": "learn",
            "translation": "v. 学习\nn. 研究", "pos": "v:1/n:1", "collins": "3",
            "oxford": "1", "tag": "cet4", "bnc": "100", "frq": "90",
            "exchange": "p:studied/d:studied/i:studying/3:studies/s:studies",
            "detail": "", "audio": "",
        })
        writer.writerow({
            "word": "newline", "translation": "n. 换行\\nn. 新的一行",
            "collins": "1", "bnc": "1000", "frq": "900",
        })
        writer.writerow({
            "word": "specialistchemical", "translation": "专业化合物",
            "collins": "0", "bnc": "0", "frq": "0",
        })
    destination = tmp_path / "dictionary.sqlite3"
    count, form_count = build(source, destination)
    assert count == 2
    assert form_count == 3
    repository = DictionaryRepository(destination)
    assert repository.warmup()
    result = repository.lookup("studies")
    assert result is not None
    assert result.lemma == "study"
    assert "v" in result.parts_of_speech
    assert repository.lookup("specialistchemical") is None
    newline = repository.lookup("newline")
    assert newline is not None
    assert newline.translations == ["n. 换行", "n. 新的一行"]


def test_word_classifier_is_strict():
    assert DictionaryRepository.is_word("don't")
    assert DictionaryRepository.is_word("well-known")
    assert not DictionaryRepository.is_word("two words")
    assert not DictionaryRepository.is_word("中文")
