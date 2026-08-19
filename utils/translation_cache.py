"""Translation cache — local hash-based lookup to avoid redundant API calls.

Stores {source_hash: result} pairs in a JSON file.  Before calling the
API the caller should check the cache first; on a miss the result is
added after translation completes.

This module is fully self-contained and has no UI dependencies.
"""

import hashlib
import json
import logging
import os
import time
from typing import Optional, Dict

from utils.debounce import DebouncedSaver

logger = logging.getLogger("cache")


class TranslationCache(DebouncedSaver):
    """Simple file-backed translation cache.

    The cache is keyed on ``sha256(text + model)`` so that changing the
    model invalidates previous entries.
    """

    def __init__(
        self,
        cache_file: str = "translation_cache.json",
        max_entries: int = 5000,
    ):
        self.cache_file = cache_file
        self.max_entries = max_entries
        self._entries: Dict[str, Dict[str, str]] = {}  # key → {result, timestamp, model}
        super().__init__()
        self.load()

    # ── persistence ────────────────────────────────────

    def load(self) -> None:
        """Load cache from disk."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._entries = data
                    logger.info("Loaded %d cache entries", len(self._entries))
            except Exception as e:
                logger.error("Error loading translation cache: %s", e)
                self._entries = {}

    def _save(self) -> None:
        """Write cache to disk."""
        try:
            entries = dict(
                sorted(
                    self._entries.items(),
                    key=lambda x: x[1].get("timestamp", ""),
                    reverse=True,
                )[: self.max_entries]
            )
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving translation cache: %s", e)

    # ── public API ─────────────────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize whitespace so trivial differences don't cause cache misses.

        Strips leading/trailing whitespace and collapses runs of
        whitespace (spaces, tabs, newlines) into single spaces.
        """
        import re
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _make_key(cls, text: str, model: str) -> str:
        """Build a deterministic cache key from normalized text + model."""
        normalized = cls._normalize_text(text)
        return hashlib.sha256(f"{model}::{normalized}".encode("utf-8")).hexdigest()

    def get(self, text: str, model: str) -> Optional[str]:
        """Return cached translation or *None*."""
        key = self._make_key(text, model)
        entry = self._entries.get(key)
        if entry and entry.get("model") == model:
            logger.debug("Cache hit for key %s…", key[:8])
            return entry["result"]
        return None

    def put(self, text: str, model: str, result: str) -> None:
        """Store a translation result."""
        key = self._make_key(text, model)
        self._entries[key] = {
            "result": result[:1000],  # cap stored size
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
        }
        self._schedule_save()

    def clear(self) -> None:
        """Remove all cached entries."""
        self._entries.clear()
        self._save()

    @property
    def size(self) -> int:
        return len(self._entries)
