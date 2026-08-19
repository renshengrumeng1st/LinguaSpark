"""Fast local dictionary provider backed by SQLite."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path
import re
import sqlite3
import threading

from learning_assistant.core.paths import bundled_dictionary_path
from learning_assistant.domain.models import DictionaryEntry


_WORD = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")


class DictionaryProvider(ABC):
    @abstractmethod
    def lookup(self, text: str, language: str = "en") -> DictionaryEntry | None:
        raise NotImplementedError


class DictionaryRepository(DictionaryProvider):
    """Read-only lookup adapter for the generated ECDICT core database."""

    def __init__(self, database_path: str | Path | None = None):
        self.path = Path(database_path) if database_path else bundled_dictionary_path()
        self._local = threading.local()

    @property
    def available(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def _connection(self) -> sqlite3.Connection | None:
        if not self.available:
            return None
        connection = getattr(self._local, "connection", None)
        if connection is None:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
        return connection

    def warmup(self) -> bool:
        """Open SQLite and touch its index during app startup, not first typing."""
        connection = self._connection()
        if connection is None:
            return False
        connection.execute("SELECT word FROM entries LIMIT 1").fetchone()
        return True

    @staticmethod
    def is_word(text: str) -> bool:
        return bool(_WORD.fullmatch(text.strip()))

    @staticmethod
    def _candidate_lemmas(word: str) -> list[str]:
        """Small fallback for forms missing from the ECDICT exchange index."""
        result = [word]
        if word.endswith("ies") and len(word) > 4:
            result.append(word[:-3] + "y")
        if word.endswith("ing") and len(word) > 5:
            stem = word[:-3]
            result.extend([stem, stem + "e"])
            if len(stem) > 2 and stem[-1] == stem[-2]:
                result.append(stem[:-1])
        if word.endswith("ed") and len(word) > 4:
            stem = word[:-2]
            result.extend([stem, stem + "e"])
            if len(stem) > 2 and stem[-1] == stem[-2]:
                result.append(stem[:-1])
        if word.endswith("es") and len(word) > 4:
            result.extend([word[:-2], word[:-1]])
        elif word.endswith("s") and len(word) > 3:
            result.append(word[:-1])
        seen: set[str] = set()
        return [item for item in result if item and not (item in seen or seen.add(item))]

    @staticmethod
    def _loads(value: str | None, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    @classmethod
    def _loads_lines(cls, value: str | None) -> list[str]:
        """Normalize both real and ECDICT-escaped newline separators."""
        loaded = cls._loads(value, [])
        if not isinstance(loaded, list):
            return []
        result: list[str] = []
        for item in loaded:
            normalized = str(item).replace("\\n", "\n")
            result.extend(line.strip() for line in normalized.splitlines() if line.strip())
        return result

    def _entry(self, row: sqlite3.Row, queried: str) -> DictionaryEntry:
        return DictionaryEntry(
            word=queried,
            lemma=row["word"],
            phonetic=row["phonetic"] or "",
            definitions=self._loads_lines(row["definitions"]),
            translations=self._loads_lines(row["translations"]),
            parts_of_speech=self._loads(row["parts_of_speech"], []),
            collocations=self._loads(row["collocations"], []),
            exchange=self._loads(row["exchange"], {}),
            frequency=row["frequency"],
            source="ECDICT",
        )

    def lookup(self, text: str, language: str = "en") -> DictionaryEntry | None:
        word = text.strip().casefold()
        if not self.is_word(word) or not language.startswith("en"):
            return None
        db = self._connection()
        if db is None:
            return None

        row = db.execute("SELECT * FROM entries WHERE word = ? COLLATE NOCASE", (word,)).fetchone()
        if row:
            return self._entry(row, word)

        form = db.execute(
            "SELECT word FROM forms WHERE form = ? COLLATE NOCASE LIMIT 1", (word,)
        ).fetchone()
        if form:
            row = db.execute(
                "SELECT * FROM entries WHERE word = ? COLLATE NOCASE", (form["word"],)
            ).fetchone()
            if row:
                return self._entry(row, word)

        for candidate in self._candidate_lemmas(word)[1:]:
            row = db.execute(
                "SELECT * FROM entries WHERE word = ? COLLATE NOCASE", (candidate,)
            ).fetchone()
            if row:
                return self._entry(row, word)
        return None
