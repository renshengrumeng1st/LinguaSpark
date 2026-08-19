"""Debounced save mixin — shared by all JSON-backed store classes.

HistoryManager, TranslationCache, and UsageStats each need to persist
state to disk, but writing on every mutation would cause excessive I/O.
This mixin provides a single ``_schedule_save`` helper that defers the
actual write until a short quiet period has elapsed.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger("debounce")


class DebouncedSaver:
    """Mixin that adds a debounced ``_schedule_save`` to any class.

    Subclasses must implement ``_save(self) -> None`` (the actual write).
    The debounce delay is configurable via ``_save_delay``.
    """

    _save_delay: float = 1.0  # seconds — subclasses may override

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._save_timer: Optional[threading.Timer] = None

    def _schedule_save(self) -> None:
        """Schedule a debounced save (cancels any previously pending one)."""
        if self._save_timer is not None:
            self._save_timer.cancel()
        timer = threading.Timer(self._save_delay, self._flush_save)
        timer.daemon = True
        self._save_timer = timer
        timer.start()

    def _flush_save(self) -> None:
        """Timer callback — delegates to the subclass ``_save``."""
        self._save_timer = None
        try:
            self._save()
        except Exception as e:
            logger.error("Debounced save failed: %s", e)

    def cancel_pending_save(self) -> None:
        """Cancel any pending save (useful in tests / shutdown)."""
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None

    def _save(self) -> None:
        """Perform the actual write — must be implemented by subclasses."""
        raise NotImplementedError
