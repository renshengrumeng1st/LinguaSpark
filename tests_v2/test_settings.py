import json
import base64
from pathlib import Path

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.domain.models import ModelProfile


class SandboxedSecretStore(SecretStore):
    """DPAPI needs the interactive Windows profile, unavailable in the test sandbox."""

    @classmethod
    def _protect(cls, plaintext: str) -> str:
        return "test:" + base64.b64encode(plaintext.encode()).decode()

    @classmethod
    def _unprotect(cls, encoded: str) -> str:
        if not encoded.startswith("test:"):
            return ""
        return base64.b64decode(encoded[5:]).decode()


def test_legacy_model_migration_separates_secret(tmp_path: Path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-secret",
        "model": "fast-model",
        "custom_models": [{
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-secret",
            "model": "fast-model",
        }],
    }), encoding="utf-8")
    public_path = tmp_path / "settings.json"
    secret_path = tmp_path / "credentials.json"
    store = SettingsStore(
        public_path,
        SandboxedSecretStore(secret_path),
        legacy,
    )
    assert store.active_model().api_key == "sk-secret"
    assert "sk-secret" not in public_path.read_text(encoding="utf-8")
    assert "sk-secret" not in secret_path.read_text(encoding="utf-8")


def test_model_crud(tmp_path: Path):
    legacy = tmp_path / "missing.json"
    store = SettingsStore(
        tmp_path / "settings.json",
        SandboxedSecretStore(tmp_path / "credentials.json"),
        legacy,
    )
    identifier = store.model_id("https://api.test/v1", "model-a")
    store.upsert_model(ModelProfile(
        id=identifier, name="Fast", base_url="https://api.test/v1",
        model="model-a", api_key="key-a",
    ))
    assert store.active_model().name == "Fast"
    store.remove_model(identifier)
    assert store.active_model() is None


def test_azure_speech_key_is_encrypted_and_separate(tmp_path: Path):
    public_path = tmp_path / "settings.json"
    secret_path = tmp_path / "credentials.json"
    store = SettingsStore(
        public_path,
        SandboxedSecretStore(secret_path),
        tmp_path / "missing.json",
    )
    store.set_azure_speech_key("speech-secret")
    assert store.azure_speech_key() == "speech-secret"
    assert "speech-secret" not in public_path.read_text(encoding="utf-8")
    assert "speech-secret" not in secret_path.read_text(encoding="utf-8")
