"""SQLite persistence for cache, history, favorites, and timings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from learning_assistant.core.paths import app_data_dir
from learning_assistant.domain.models import LearningItem, ReviewRating


class LearningRepository:
    def __init__(self, database_path: str | Path | None = None):
        self.path = Path(database_path) if database_path else app_data_dir() / "learning.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._local.connection = connection
        return connection

    def _initialize(self) -> None:
        db = self._connection()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_text TEXT NOT NULL,
                query_kind TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS favorites (
                item_key TEXT PRIMARY KEY,
                source_text TEXT NOT NULL,
                query_kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id TEXT NOT NULL,
                query_kind TEXT NOT NULL,
                first_byte_ms INTEGER,
                total_ms INTEGER NOT NULL,
                success INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning_items (
                item_key TEXT PRIMARY KEY,
                source_text TEXT NOT NULL,
                query_kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                due_at INTEGER NOT NULL,
                interval_days INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                last_reviewed_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS review_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_key TEXT NOT NULL REFERENCES learning_items(item_key) ON DELETE CASCADE,
                rating TEXT NOT NULL,
                reviewed_at INTEGER NOT NULL,
                previous_due_at INTEGER NOT NULL,
                next_due_at INTEGER NOT NULL,
                interval_days INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_created ON query_history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_metrics_provider ON request_metrics(provider_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_learning_due ON learning_items(due_at);
            CREATE INDEX IF NOT EXISTS idx_review_item ON review_logs(item_key, reviewed_at DESC);
            """
        )
        db.commit()

    @staticmethod
    def stable_key(*parts: Any) -> str:
        material = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get_ai_cache(self, key: str) -> dict[str, Any] | None:
        row = self._connection().execute(
            "SELECT payload FROM ai_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload"])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    def put_ai_cache(self, key: str, payload: dict[str, Any]) -> None:
        self._connection().execute(
            "INSERT OR REPLACE INTO ai_cache(cache_key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), int(time.time())),
        )
        self._connection().commit()

    def add_history(
        self,
        source_text: str,
        query_kind: str,
        result: dict[str, Any],
        source_language: str,
        target_language: str,
    ) -> None:
        self._connection().execute(
            """INSERT INTO query_history(
                source_text, query_kind, result_json, source_language,
                target_language, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                source_text[:4000], query_kind,
                json.dumps(result, ensure_ascii=False), source_language,
                target_language, int(time.time()),
            ),
        )
        self._connection().commit()

    def toggle_favorite(
        self, source_text: str, query_kind: str, payload: dict[str, Any], context: str = ""
    ) -> bool:
        key = self.stable_key(query_kind, source_text.casefold())
        db = self._connection()
        exists = db.execute("SELECT 1 FROM favorites WHERE item_key = ?", (key,)).fetchone()
        if exists:
            db.execute("DELETE FROM favorites WHERE item_key = ?", (key,))
            db.commit()
            return False
        db.execute(
            "INSERT INTO favorites VALUES (?, ?, ?, ?, ?, ?)",
            (
                key, source_text, query_kind, json.dumps(payload, ensure_ascii=False),
                context[:2000], int(time.time()),
            ),
        )
        db.commit()
        return True

    def is_favorite(self, source_text: str, query_kind: str) -> bool:
        key = self.stable_key(query_kind, source_text.casefold())
        row = self._connection().execute(
            "SELECT 1 FROM favorites WHERE item_key = ?", (key,)
        ).fetchone()
        return bool(row)

    @staticmethod
    def _learning_item(row: sqlite3.Row) -> LearningItem:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        return LearningItem(
            item_key=row["item_key"],
            source_text=row["source_text"],
            query_kind=row["query_kind"],
            payload=payload if isinstance(payload, dict) else {},
            context=row["context"],
            source_language=row["source_language"],
            target_language=row["target_language"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            due_at=row["due_at"],
            interval_days=row["interval_days"],
            streak=row["streak"],
            lapses=row["lapses"],
            last_reviewed_at=row["last_reviewed_at"],
        )

    def toggle_learning_item(
        self,
        source_text: str,
        query_kind: str,
        payload: dict[str, Any],
        context: str = "",
        source_language: str = "en",
        target_language: str = "zh-CN",
        now: int | None = None,
    ) -> bool:
        key = self.stable_key(query_kind, source_text.casefold())
        db = self._connection()
        if db.execute("SELECT 1 FROM learning_items WHERE item_key = ?", (key,)).fetchone():
            db.execute("DELETE FROM learning_items WHERE item_key = ?", (key,))
            db.commit()
            return False
        timestamp = int(time.time()) if now is None else int(now)
        db.execute(
            """INSERT INTO learning_items(
                item_key, source_text, query_kind, payload, context,
                source_language, target_language, created_at, updated_at, due_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key, source_text, query_kind, json.dumps(payload, ensure_ascii=False),
                context[:2000], source_language, target_language,
                timestamp, timestamp, timestamp,
            ),
        )
        db.commit()
        return True

    def is_learning_item(self, source_text: str, query_kind: str) -> bool:
        key = self.stable_key(query_kind, source_text.casefold())
        return bool(self._connection().execute(
            "SELECT 1 FROM learning_items WHERE item_key = ?", (key,)
        ).fetchone())

    def update_learning_payload(
        self, source_text: str, query_kind: str, payload: dict[str, Any]
    ) -> None:
        key = self.stable_key(query_kind, source_text.casefold())
        self._connection().execute(
            "UPDATE learning_items SET payload = ?, updated_at = ? WHERE item_key = ?",
            (json.dumps(payload, ensure_ascii=False), int(time.time()), key),
        )
        self._connection().commit()

    def due_learning_items(
        self, limit: int = 50, now: int | None = None
    ) -> list[LearningItem]:
        timestamp = int(time.time()) if now is None else int(now)
        rows = self._connection().execute(
            """SELECT * FROM learning_items
               WHERE due_at <= ? ORDER BY due_at, created_at LIMIT ?""",
            (timestamp, max(1, int(limit))),
        ).fetchall()
        return [self._learning_item(row) for row in rows]

    def due_learning_count(self, now: int | None = None) -> int:
        timestamp = int(time.time()) if now is None else int(now)
        row = self._connection().execute(
            "SELECT COUNT(*) AS total FROM learning_items WHERE due_at <= ?", (timestamp,)
        ).fetchone()
        return int(row["total"])

    def review_item(
        self,
        item_key: str,
        rating: ReviewRating | str,
        now: int | None = None,
    ) -> LearningItem:
        rating = ReviewRating(rating)
        timestamp = int(time.time()) if now is None else int(now)
        db = self._connection()
        row = db.execute("SELECT * FROM learning_items WHERE item_key = ?", (item_key,)).fetchone()
        if not row:
            raise KeyError(item_key)
        current = self._learning_item(row)
        streak = current.streak
        lapses = current.lapses
        if rating == ReviewRating.AGAIN:
            interval_days = 0
            due_at = timestamp + 10 * 60
            streak = 0
            lapses += 1
        elif rating == ReviewRating.HARD:
            interval_days = 1 if current.interval_days <= 0 else max(
                1, round(current.interval_days * 1.5)
            )
            due_at = timestamp + interval_days * 86400
        else:
            streak += 1
            intervals = (3, 7, 14, 30, 60, 120)
            interval_days = intervals[min(streak - 1, len(intervals) - 1)]
            due_at = timestamp + interval_days * 86400
        db.execute(
            """UPDATE learning_items SET due_at = ?, interval_days = ?, streak = ?,
               lapses = ?, last_reviewed_at = ?, updated_at = ? WHERE item_key = ?""",
            (due_at, interval_days, streak, lapses, timestamp, timestamp, item_key),
        )
        db.execute(
            """INSERT INTO review_logs(
                item_key, rating, reviewed_at, previous_due_at, next_due_at, interval_days
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (item_key, rating.value, timestamp, current.due_at, due_at, interval_days),
        )
        db.commit()
        updated = db.execute("SELECT * FROM learning_items WHERE item_key = ?", (item_key,)).fetchone()
        return self._learning_item(updated)

    def record_metric(
        self,
        provider_id: str,
        query_kind: str,
        first_byte_ms: int | None,
        total_ms: int,
        success: bool,
    ) -> None:
        self._connection().execute(
            "INSERT INTO request_metrics VALUES (NULL, ?, ?, ?, ?, ?, ?)",
            (provider_id, query_kind, first_byte_ms, total_ms, int(success), int(time.time())),
        )
        self._connection().commit()
