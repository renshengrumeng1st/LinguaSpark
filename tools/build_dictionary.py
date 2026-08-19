"""Build the compact runtime dictionary from ECDICT's CSV export.

Usage:
    python tools/build_dictionary.py path/to/ecdict.csv data/ecdict_core.sqlite3

Only English headwords useful to learners are retained.  The resulting
database is queried read-only at runtime and normally contains tens of
thousands of high-frequency entries rather than the entire specialist corpus.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import sqlite3
import sys


WORD = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
POS_PREFIX = re.compile(r"^(n|v|vt|vi|adj|adv|prep|pron|conj|num|art|aux|int)\.", re.I)
EXCHANGE_NAMES = {
    "p": "past", "d": "past_participle", "i": "present_participle",
    "3": "third_person", "s": "plural", "r": "comparative", "t": "superlative",
}


def lines(value: str) -> list[str]:
    return [
        line.strip()
        for line in (value or "").replace("\\n", "\n").splitlines()
        if line.strip()
    ]


def parts_of_speech(row: dict[str, str], translations: list[str]) -> list[str]:
    values: list[str] = []
    for item in re.split(r"[/, ]+", row.get("pos", "")):
        name = item.split(":", 1)[0].strip().rstrip(".")
        if name and len(name) <= 8:
            values.append(name)
    for item in translations:
        match = POS_PREFIX.match(item)
        if match:
            values.append(match.group(1).lower())
    return list(dict.fromkeys(values))


def exchange(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in (value or "").split("/"):
        if ":" not in item:
            continue
        key, form = item.split(":", 1)
        name = EXCHANGE_NAMES.get(key.strip())
        if name and form.strip():
            result[name] = form.strip()
    return result


def integer(value: str) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def should_keep(row: dict[str, str]) -> bool:
    word = row.get("word", "").strip()
    if not WORD.fullmatch(word) or not row.get("translation", "").strip():
        return False
    collins = integer(row.get("collins", ""))
    bnc = integer(row.get("bnc", ""))
    frq = integer(row.get("frq", ""))
    tagged = bool(row.get("tag", "").strip() or row.get("oxford", "").strip())
    return bool(collins or tagged or (bnc and bnc <= 60000) or (frq and frq <= 60000))


def build(source: Path, destination: Path) -> tuple[int, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    db = sqlite3.connect(destination)
    db.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE entries (
            word TEXT PRIMARY KEY COLLATE NOCASE,
            phonetic TEXT NOT NULL DEFAULT '',
            definitions TEXT NOT NULL DEFAULT '[]',
            translations TEXT NOT NULL DEFAULT '[]',
            parts_of_speech TEXT NOT NULL DEFAULT '[]',
            collocations TEXT NOT NULL DEFAULT '[]',
            exchange TEXT NOT NULL DEFAULT '{}',
            frequency INTEGER
        ) WITHOUT ROWID;
        CREATE TABLE forms (
            form TEXT NOT NULL COLLATE NOCASE,
            word TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY(form, word)
        ) WITHOUT ROWID;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    kept = forms = 0
    csv.field_size_limit(sys.maxsize)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not should_keep(row):
                continue
            word = row["word"].strip().casefold()
            translations = lines(row.get("translation", ""))
            definitions = lines(row.get("definition", ""))
            changes = exchange(row.get("exchange", ""))
            frequency = integer(row.get("bnc", "")) or integer(row.get("frq", ""))
            db.execute(
                "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    word, row.get("phonetic", "").strip(),
                    json.dumps(definitions, ensure_ascii=False),
                    json.dumps(translations, ensure_ascii=False),
                    json.dumps(parts_of_speech(row, translations), ensure_ascii=False),
                    "[]", json.dumps(changes, ensure_ascii=False), frequency,
                ),
            )
            kept += 1
            for form_group in changes.values():
                for form in form_group.split(","):
                    form = form.strip().casefold()
                    if WORD.fullmatch(form):
                        db.execute("INSERT OR IGNORE INTO forms VALUES (?, ?)", (form, word))
                        forms += 1
            if kept % 5000 == 0:
                db.commit()
    forms = int(db.execute("SELECT COUNT(*) FROM forms").fetchone()[0])
    db.executemany(
        "INSERT INTO metadata VALUES (?, ?)",
        [("source", "ECDICT"), ("license", "MIT"), ("entries", str(kept))],
    )
    db.executescript(
        "CREATE INDEX idx_forms_form ON forms(form COLLATE NOCASE); VACUUM;"
    )
    db.close()
    return kept, forms


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_dictionary.py SOURCE_CSV DESTINATION_SQLITE")
    count, form_count = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"built {count} entries and {form_count} forms")
