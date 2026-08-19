"""Public settings and encrypted credentials.

API keys never belong in the distributable config.  On Windows they are
protected with DPAPI for the current user and stored separately from model
metadata.  The first launch imports the legacy config without changing it.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from learning_assistant.core.paths import app_data_dir, project_root
from learning_assistant.domain.models import LanguageProfile, ModelProfile


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 2,
    "active_model_id": "",
    "models": [],
    "languages": {"source": "en", "target": "zh-CN", "explanation": "zh-CN"},
    "auto_lookup_delay_ms": 160,
    "selection_hotkey": "alt+w",
    "window_hotkey": "alt+q",
    "review_reminders": True,
    "last_review_notice_date": "",
    "tts": {
        "provider": "sapi",
        "voice_locale": "en-US",
        "rate": -1,
        "azure_region": "",
    },
}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class SecretStore:
    """Small JSON credential store backed by Windows DPAPI."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else app_data_dir() / "credentials.json"
        self._lock = threading.RLock()
        self._values: dict[str, str] = {}
        self._load()

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        return blob, buffer

    @classmethod
    def _protect(cls, plaintext: str) -> str:
        raw = plaintext.encode("utf-8")
        if os.name != "nt":
            return "plain:" + base64.b64encode(raw).decode("ascii")
        in_blob, _ = cls._blob(raw)
        out_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob), "LinguaSpark", None, None, None, 0,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return "dpapi:" + base64.b64encode(protected).decode("ascii")
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def _unprotect(cls, encoded: str) -> str:
        if encoded.startswith("plain:"):
            return base64.b64decode(encoded[6:]).decode("utf-8")
        if not encoded.startswith("dpapi:") or os.name != "nt":
            return ""
        protected = base64.b64decode(encoded[6:])
        in_blob, _ = cls._blob(protected)
        out_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0,
            ctypes.byref(out_blob),
        ):
            return ""
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                self._values = {str(k): str(v) for k, v in value.items()}
        except (OSError, ValueError):
            self._values = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    def get(self, key: str) -> str:
        with self._lock:
            return self._unprotect(self._values.get(key, ""))

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if value:
                self._values[key] = self._protect(value)
            else:
                self._values.pop(key, None)
            self._save()

    def delete(self, key: str) -> None:
        self.set(key, "")


class SettingsStore:
    def __init__(
        self,
        path: str | Path | None = None,
        secrets: SecretStore | None = None,
        legacy_path: str | Path | None = None,
    ):
        self.path = Path(path) if path else app_data_dir() / "settings.json"
        self.secrets = secrets or SecretStore()
        self.legacy_path = Path(legacy_path) if legacy_path else project_root() / "config.json"
        self._lock = threading.RLock()
        self._data = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    @staticmethod
    def model_id(base_url: str, model: str) -> str:
        value = f"{base_url.rstrip('/').casefold()}::{model.casefold()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def load(self) -> dict[str, Any]:
        with self._lock:
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._data.update(loaded)
                except (OSError, ValueError):
                    pass
            else:
                self._import_legacy()
                self.save()
            self._normalize()
            return self._data

    def _normalize(self) -> None:
        if not isinstance(self._data.get("models"), list):
            self._data["models"] = []
        languages = self._data.get("languages")
        if not isinstance(languages, dict):
            self._data["languages"] = dict(DEFAULT_SETTINGS["languages"])
        tts = self._data.get("tts")
        if not isinstance(tts, dict):
            self._data["tts"] = dict(DEFAULT_SETTINGS["tts"])

    def _import_legacy(self) -> None:
        if not self.legacy_path.exists():
            return
        try:
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = legacy.get("custom_models", [])
        if not isinstance(entries, list):
            entries = []
        if not entries and all(legacy.get(k) for k in ("base_url", "api_key", "model")):
            entries = [{k: legacy.get(k, "") for k in ("base_url", "api_key", "model")}]
        models: list[dict[str, Any]] = []
        active_name = str(legacy.get("model", ""))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            base_url = str(entry.get("base_url", "")).strip()
            model = str(entry.get("model", "")).strip()
            api_key = str(entry.get("api_key", "")).strip()
            if not base_url or not model:
                continue
            identifier = self.model_id(base_url, model)
            models.append({
                "id": identifier, "name": model, "base_url": base_url,
                "model": model, "enabled": True,
            })
            if api_key:
                self.secrets.set(f"model:{identifier}:api_key", api_key)
            if model == active_name:
                self._data["active_model_id"] = identifier
        self._data["models"] = models
        self._data["window_hotkey"] = str(legacy.get("hotkey", "alt+q"))
        self._data["selection_hotkey"] = str(legacy.get("shortcut_select", "<Alt-W>"))
        if models and not self._data["active_model_id"]:
            self._data["active_model_id"] = models[0]["id"]

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def languages(self) -> LanguageProfile:
        value = self._data.get("languages", {})
        return LanguageProfile(
            source=str(value.get("source", "en")),
            target=str(value.get("target", "zh-CN")),
            explanation=str(value.get("explanation", "zh-CN")),
        )

    def models(self) -> list[ModelProfile]:
        result: list[ModelProfile] = []
        for item in self._data.get("models", []):
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("id", ""))
            if not identifier:
                continue
            result.append(ModelProfile(
                id=identifier,
                name=str(item.get("name", item.get("model", ""))),
                base_url=str(item.get("base_url", "")),
                model=str(item.get("model", "")),
                api_key=self.secrets.get(f"model:{identifier}:api_key"),
                enabled=bool(item.get("enabled", True)),
            ))
        return result

    def active_model(self) -> ModelProfile | None:
        active = str(self._data.get("active_model_id", ""))
        return next((model for model in self.models() if model.id == active), None)

    def upsert_model(self, profile: ModelProfile, make_active: bool = True) -> None:
        identifier = profile.id or self.model_id(profile.base_url, profile.model)
        public = {
            "id": identifier,
            "name": profile.name or profile.model,
            "base_url": profile.base_url.rstrip("/"),
            "model": profile.model,
            "enabled": profile.enabled,
        }
        models = self._data.setdefault("models", [])
        for index, item in enumerate(models):
            if item.get("id") == identifier:
                models[index] = public
                break
        else:
            models.append(public)
        self.secrets.set(f"model:{identifier}:api_key", profile.api_key)
        if make_active:
            self._data["active_model_id"] = identifier
        self.save()

    def remove_model(self, identifier: str) -> None:
        self._data["models"] = [
            item for item in self._data.get("models", []) if item.get("id") != identifier
        ]
        self.secrets.delete(f"model:{identifier}:api_key")
        if self._data.get("active_model_id") == identifier:
            models = self._data["models"]
            self._data["active_model_id"] = models[0]["id"] if models else ""
        self.save()

    def select_model(self, identifier: str) -> bool:
        if any(item.get("id") == identifier for item in self._data.get("models", [])):
            self._data["active_model_id"] = identifier
            self.save()
            return True
        return False

    def azure_speech_key(self) -> str:
        return self.secrets.get("tts:azure:key")

    def set_azure_speech_key(self, value: str) -> None:
        self.secrets.set("tts:azure:key", value.strip())
