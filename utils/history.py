"""Translation history manager — stores and retrieves past translations."""

import json
import logging
import os
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from utils.debounce import DebouncedSaver

logger = logging.getLogger("history")


@dataclass
class HistoryEntry:
    """Single translation history entry."""
    timestamp: str
    source_text: str
    result_text: str
    has_image: bool
    model: str
    favorite: bool = False
    id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HistoryEntry":
        # Tolerate older entries that lack the favorite/id fields.
        return cls(
            timestamp=d.get("timestamp", ""),
            source_text=d.get("source_text", ""),
            result_text=d.get("result_text", ""),
            has_image=d.get("has_image", False),
            model=d.get("model", ""),
            favorite=d.get("favorite", False),
            id=d.get("id", ""),
        )


class HistoryManager(DebouncedSaver):
    """Manages translation history persistence (JSON file based)."""

    _save_delay = 2.0  # History changes are less frequent — longer debounce

    def __init__(self, history_file: str = "translation_history.json", max_entries: int = 100):
        self.history_file = history_file
        self.max_entries = max_entries
        self._entries: List[HistoryEntry] = []
        super().__init__()
        self.load()

    def load(self) -> None:
        """Load history from file."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = [HistoryEntry.from_dict(e) for e in data]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Error loading history: %s", e)
                self._entries = []
        else:
            self._entries = []

    def save(self) -> bool:
        """Persist history to file immediately."""
        try:
            entries = [e.to_dict() for e in self._entries[-self.max_entries:]]
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Error saving history: %s", e)
            return False

    def _save(self) -> None:
        """DebouncedSaver callback — delegates to save()."""
        self.save()

    def add(
        self,
        source_text: str,
        result_text: str,
        has_image: bool,
        model: str = "",
    ) -> HistoryEntry:
        """Add a new history entry (schedules debounced save)."""
        entry = HistoryEntry(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            source_text=source_text[:500],  # Limit stored text length
            result_text=result_text[:500],
            has_image=has_image,
            model=model,
            favorite=False,
            id=uuid.uuid4().hex,
        )
        self._entries.append(entry)
        # Keep only the latest entries
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]
        self._schedule_save()
        return entry

    def get_all(self) -> List[HistoryEntry]:
        """Return all entries, newest first."""
        return list(reversed(self._entries))

    def get_recent(self, count: int = 10) -> List[HistoryEntry]:
        """Return the most recent N entries."""
        return list(reversed(self._entries[-count:]))

    def clear(self) -> bool:
        """Clear all history."""
        self._entries = []
        return self.save()

    def delete_entry(self, entry: "HistoryEntry") -> bool:
        """Delete a single history entry (matches by object identity)."""
        if entry in self._entries:
            self._entries.remove(entry)
            self.save()  # persist immediately — deliberate user action
            return True
        return False

    def toggle_favorite(self, entry: "HistoryEntry") -> bool:
        """Flip the favorite flag on an entry and persist it."""
        entry.favorite = not entry.favorite
        self.save()  # persist immediately — deliberate user action
        return entry.favorite

    def search(self, keyword: str) -> List[HistoryEntry]:
        """Search entries containing keyword (case-insensitive)."""
        keyword_lower = keyword.lower()
        results = []
        for entry in reversed(self._entries):
            if (keyword_lower in entry.source_text.lower() or
                    keyword_lower in entry.result_text.lower()):
                results.append(entry)
        return results
