"""Language-neutral domain objects.

The previous application passed Markdown strings between every layer.  These
models keep facts, AI guidance, and presentation separate, which is essential
for future Japanese/French/etc. providers and for reliable speech playback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class QueryKind(str, Enum):
    WORD = "word"
    SENTENCE = "sentence"
    IMAGE = "image"


class ReviewRating(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    source: str = "en"
    target: str = "zh-CN"
    explanation: str = "zh-CN"


@dataclass(slots=True)
class ModelProfile:
    id: str
    name: str
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    enabled: bool = True

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("api_key", None)
        return data


@dataclass(slots=True)
class DictionaryEntry:
    word: str
    lemma: str = ""
    phonetic: str = ""
    definitions: list[str] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    parts_of_speech: list[str] = field(default_factory=list)
    collocations: list[str] = field(default_factory=list)
    exchange: dict[str, str] = field(default_factory=dict)
    frequency: int | None = None
    source: str = ""

    @property
    def display_word(self) -> str:
        return self.lemma or self.word

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "lemma": self.lemma,
            "phonetic": self.phonetic,
            "definitions": self.definitions[:6],
            "translations": self.translations[:8],
            "parts_of_speech": self.parts_of_speech[:6],
            "collocations": self.collocations[:6],
        }


@dataclass(slots=True)
class AiStudyNote:
    plain_explanation: str = ""
    sense_in_context: str = ""
    synonyms: list[str] = field(default_factory=list)
    collocations: list[str] = field(default_factory=list)
    common_mistake: str = ""
    memory_tip: str = ""
    examples: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AiStudyNote":
        value = value if isinstance(value, dict) else {}

        def strings(key: str, limit: int = 8) -> list[str]:
            raw = value.get(key, [])
            if isinstance(raw, str):
                raw = [raw]
            return [str(item).strip() for item in raw if str(item).strip()][:limit]

        examples: list[dict[str, str]] = []
        for item in value.get("examples", []) if isinstance(value.get("examples", []), list) else []:
            if isinstance(item, dict):
                sentence = str(item.get("sentence", "")).strip()
                translation = str(item.get("translation", "")).strip()
            else:
                sentence, translation = str(item).strip(), ""
            if sentence:
                examples.append({"sentence": sentence, "translation": translation})
        return cls(
            plain_explanation=str(value.get("plain_explanation", "")).strip(),
            sense_in_context=str(value.get("sense_in_context", "")).strip(),
            synonyms=strings("synonyms"),
            collocations=strings("collocations"),
            common_mistake=str(value.get("common_mistake", "")).strip(),
            memory_tip=str(value.get("memory_tip", "")).strip(),
            examples=examples[:4],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SentenceResult:
    translation: str = ""
    key_phrases: list[dict[str, str]] = field(default_factory=list)
    learning_tip: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "SentenceResult":
        value = value if isinstance(value, dict) else {}
        phrases: list[dict[str, str]] = []
        raw_phrases = value.get("key_phrases", [])
        if isinstance(raw_phrases, list):
            for item in raw_phrases[:6]:
                if isinstance(item, dict):
                    phrase = str(item.get("phrase", "")).strip()
                    meaning = str(item.get("meaning", "")).strip()
                    if phrase:
                        phrases.append({"phrase": phrase, "meaning": meaning})
        return cls(
            translation=str(value.get("translation", "")).strip(),
            key_phrases=phrases,
            learning_tip=str(value.get("learning_tip", "")).strip(),
        )


@dataclass(slots=True)
class QueryRequest:
    text: str
    kind: QueryKind
    languages: LanguageProfile = field(default_factory=LanguageProfile)
    context: str = ""
    image_bytes: bytes | None = field(default=None, repr=False)


@dataclass(slots=True)
class LearningItem:
    item_key: str
    source_text: str
    query_kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    context: str = ""
    source_language: str = "en"
    target_language: str = "zh-CN"
    created_at: int = 0
    updated_at: int = 0
    due_at: int = 0
    interval_days: int = 0
    streak: int = 0
    lapses: int = 0
    last_reviewed_at: int | None = None
