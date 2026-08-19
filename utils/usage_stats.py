"""Usage statistics — tracks translation counts, characters, and estimates cost.

Persists a small JSON file alongside the config.  The ``cost_per_1k``
mapping is approximate and can be overridden in the config under
``cost_overrides``.
"""

import json
import logging
import os
import time
from typing import Dict, Optional

from utils.debounce import DebouncedSaver

logger = logging.getLogger("stats")

# Rough per-1000-character cost in CNY (text input only)
DEFAULT_COST_PER_1K: Dict[str, float] = {
    "gpt-4o-mini": 0.01,
    "gpt-4o": 0.15,
    "deepseek-chat": 0.005,
    "deepseek-reasoner": 0.01,
    "deepseek-v4-flash": 0.002,
    "Qwen/Qwen2.5-VL-72B-Instruct": 0.02,
    "Qwen/Qwen2.5-VL-32B-Instruct": 0.01,
    "deepseek-ai/deepseek-vl2": 0.02,
    "Pro/Qwen/Qwen2-VL-7B-Instruct": 0.005,
}


class UsageStats(DebouncedSaver):
    """Tracks usage statistics persisted to a JSON file."""

    def __init__(
        self,
        stats_file: str = "usage_stats.json",
        cost_overrides: Optional[Dict[str, float]] = None,
    ):
        self.stats_file = stats_file
        self._cost_per_1k: Dict[str, float] = {
            **DEFAULT_COST_PER_1K,
            **(cost_overrides or {}),
        }
        self._data: Dict[str, any] = {
            "total_translations": 0,
            "total_characters": 0,
            "text_translations": 0,
            "image_translations": 0,
            "cache_hits": 0,
            "daily": {},  # "YYYY-MM-DD" → {count, chars, cost}
            "per_model": {},  # model → {count, chars}
        }
        super().__init__()
        self.load()

    # ── persistence ────────────────────────────────────

    def load(self) -> None:
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge with defaults so new fields are always present
                self._data = {**self._data, **loaded}
            except Exception as e:
                logger.error("Error loading usage stats: %s", e)

    def _save(self) -> None:
        try:
            with open(self.stats_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving usage stats: %s", e)

    # ── recording ──────────────────────────────────────

    def record(
        self,
        model: str,
        char_count: int,
        has_image: bool = False,
        cache_hit: bool = False,
    ) -> None:
        """Record one translation event."""
        today = time.strftime("%Y-%m-%d")

        self._data["total_translations"] += 1
        self._data["total_characters"] += char_count

        if cache_hit:
            self._data["cache_hits"] += 1
        if has_image:
            self._data["image_translations"] += 1
        else:
            self._data["text_translations"] += 1

        # Daily breakdown
        daily = self._data["daily"].setdefault(
            today, {"count": 0, "chars": 0, "cost": 0.0}
        )
        daily["count"] += 1
        daily["chars"] += char_count
        cost = self._estimate_cost(model, char_count, has_image, cache_hit)
        daily["cost"] = round(daily["cost"] + cost, 4)

        # Per-model breakdown
        per_model = self._data["per_model"].setdefault(
            model, {"count": 0, "chars": 0}
        )
        per_model["count"] += 1
        per_model["chars"] += char_count

        self._schedule_save()

    def record_cache_hit(self) -> None:
        """Record a cache hit (no API call was made)."""
        self._data["cache_hits"] += 1
        self._schedule_save()

    def _estimate_cost(
        self, model: str, char_count: int, has_image: bool, cache_hit: bool
    ) -> float:
        """Estimate API cost in CNY for a single translation."""
        if cache_hit:
            return 0.0
        rate = self._cost_per_1k.get(model, 0.01)
        cost = (char_count / 1000) * rate
        if has_image:
            cost *= 3  # images are ~3× more expensive
        return cost

    # ── queries ────────────────────────────────────────

    def get_summary(self) -> Dict[str, any]:
        """Return a summary suitable for display."""
        today = time.strftime("%Y-%m-%d")
        daily = self._data["daily"].get(today, {"count": 0, "chars": 0, "cost": 0.0})
        month = today[:7]  # "YYYY-MM"
        month_total = {"count": 0, "chars": 0, "cost": 0.0}
        for date, d in self._data["daily"].items():
            if date.startswith(month):
                month_total["count"] += d["count"]
                month_total["chars"] += d["chars"]
                month_total["cost"] = round(month_total["cost"] + d["cost"], 4)

        return {
            "total_translations": self._data["total_translations"],
            "total_characters": self._data["total_characters"],
            "cache_hits": self._data["cache_hits"],
            "text_translations": self._data["text_translations"],
            "image_translations": self._data["image_translations"],
            "today": daily,
            "month": month_total,
        }

    def clear(self) -> None:
        """Reset all statistics."""
        self._data = {
            "total_translations": 0,
            "total_characters": 0,
            "text_translations": 0,
            "image_translations": 0,
            "cache_hits": 0,
            "daily": {},
            "per_model": {},
        }
        self._save()
