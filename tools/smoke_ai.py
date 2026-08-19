"""Minimal real-provider smoke test; never prints credentials or content."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer

from learning_assistant.controller import LearningController
from learning_assistant.core.settings import SettingsStore
from learning_assistant.services.dictionary import DictionaryRepository
from learning_assistant.storage.learning_repository import LearningRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Good morning. This is a connection test.")
    parser.add_argument("--database", type=Path, default=Path("ai-smoke.sqlite3"))
    args = parser.parse_args()

    app = QCoreApplication(sys.argv[:1])
    dictionary = DictionaryRepository()
    dictionary.warmup()
    controller = LearningController(
        settings=SettingsStore(),
        dictionary=dictionary,
        repository=LearningRepository(args.database),
    )
    started = time.perf_counter()
    state = {"ok": False, "chars": 0, "error": "", "kind": "", "local_ms": None}

    def ready(result, cache_hit: bool) -> None:
        state["ok"] = bool(result.translation)
        state["chars"] = len(result.translation)
        state["kind"] = "sentence"

    def word_ready(entry, elapsed_ms: int) -> None:
        state["local_ms"] = elapsed_ms

    def note_ready(note, cache_hit: bool) -> None:
        payload = note.to_dict()
        state["ok"] = any(bool(value) for value in payload.values())
        state["chars"] = len(note.plain_explanation)
        state["kind"] = "word"

    def failed(message: str) -> None:
        state["error"] = message
        app.exit(2)

    def finished(info: object) -> None:
        app.quit()

    controller.sentence_ready.connect(ready)
    controller.word_ready.connect(word_ready)
    controller.ai_note_ready.connect(note_ready)
    controller.query_failed.connect(failed)
    controller.query_finished.connect(finished)
    QTimer.singleShot(45_000, lambda: app.exit(3))
    QTimer.singleShot(0, lambda: controller.submit(args.text))
    code = app.exec()
    elapsed = round((time.perf_counter() - started) * 1000)
    if code == 0 and state["ok"]:
        local = "-" if state["local_ms"] is None else str(state["local_ms"])
        print(
            f"ai-smoke-ok kind={state['kind']} chars={state['chars']} "
            f"local_ms={local} elapsed_ms={elapsed}"
        )
        return 0
    print(f"ai-smoke-failed code={code} message={state['error'] or 'timeout'}")
    return code or 4


if __name__ == "__main__":
    raise SystemExit(main())
