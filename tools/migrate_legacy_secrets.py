"""Move legacy plaintext API keys into the Windows DPAPI credential store.

The source file is sanitized only after every non-empty key can be read back
from the encrypted store. No plaintext backup is created intentionally.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import ModelProfile


def migrate(path: Path, apply: bool = False) -> tuple[int, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    entries = value.get("custom_models", [])
    if not isinstance(entries, list):
        entries = []
    top = {key: value.get(key, "") for key in ("base_url", "model", "api_key")}
    if all(str(top[key]).strip() for key in ("base_url", "model")):
        identifiers = {
            (str(item.get("base_url", "")).strip(), str(item.get("model", "")).strip())
            for item in entries if isinstance(item, dict)
        }
        if (str(top["base_url"]).strip(), str(top["model"]).strip()) not in identifiers:
            entries.append(top)

    candidates: list[ModelProfile] = []
    active_model = str(value.get("model", "")).strip()
    for item in entries:
        if not isinstance(item, dict):
            continue
        base_url = str(item.get("base_url", "")).strip()
        model = str(item.get("model", "")).strip()
        key = str(item.get("api_key", "")).strip()
        if not base_url or not model or not key:
            continue
        identifier = SettingsStore.model_id(base_url, model)
        candidates.append(ModelProfile(identifier, model, base_url, model, key))

    if not apply:
        return len(candidates), 0

    store = SettingsStore(legacy_path=path)
    for profile in candidates:
        store.upsert_model(profile, make_active=profile.model == active_model)
    saved = {profile.id: profile for profile in store.models()}
    verified = sum(
        1 for profile in candidates
        if profile.id in saved and saved[profile.id].api_key == profile.api_key
    )
    if verified != len(candidates):
        raise RuntimeError("Encrypted credential verification failed; legacy file was not changed")

    value["api_key"] = ""
    for item in value.get("custom_models", []):
        if isinstance(item, dict):
            item["api_key"] = ""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return len(candidates), verified


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=Path("config.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    found, verified = migrate(args.path, args.apply)
    print(f"credentials found={found}, verified={verified}, sanitized={bool(args.apply)}")
