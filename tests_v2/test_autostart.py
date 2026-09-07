from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from learning_assistant.core.settings import SecretStore, SettingsStore
from learning_assistant.ui.settings_dialog import SettingsDialog


class MemoryStartupRegistry:
    def __init__(self, value: str | None = None, fail_writes: bool = False):
        self.value = value
        self.fail_writes = fail_writes

    def read(self) -> str | None:
        return self.value

    def write(self, value: str) -> None:
        if self.fail_writes:
            raise OSError("registry denied")
        self.value = value

    def delete(self) -> None:
        if self.fail_writes:
            raise OSError("registry denied")
        self.value = None


def _autostart_api():
    try:
        return importlib.import_module("learning_assistant.services.autostart")
    except ModuleNotFoundError as error:
        pytest.fail(f"autostart service is missing: {error}")


def _settings(tmp_path: Path) -> SettingsStore:
    return SettingsStore(
        tmp_path / "settings.json",
        SecretStore(tmp_path / "credentials.json"),
        tmp_path / "missing.json",
    )


def test_packaged_startup_command_quotes_paths_with_spaces() -> None:
    autostart = _autostart_api()

    command = autostart.build_startup_command(
        Path(r"C:\Program Files\LinguaSpark\LinguaSpark.exe")
    )

    assert command == '"C:\\Program Files\\LinguaSpark\\LinguaSpark.exe" --startup'


def test_source_startup_command_uses_pythonw_and_absolute_entrypoint(tmp_path: Path) -> None:
    autostart = _autostart_api()
    python = tmp_path / "Python Runtime" / "python.exe"
    python.parent.mkdir()
    python.write_bytes(b"")
    python.with_name("pythonw.exe").write_bytes(b"")
    entrypoint = tmp_path / "Lingua Spark" / "main.py"

    command = autostart.build_startup_command(python, entrypoint)

    assert command == (
        f'"{python.with_name("pythonw.exe")}" '
        f'"{entrypoint}" --startup'
    )


def test_service_enables_and_disables_current_user_startup() -> None:
    autostart = _autostart_api()
    registry = MemoryStartupRegistry()
    command = '"C:\\Apps\\LinguaSpark.exe" --startup'
    service = autostart.AutostartService(command, registry)

    assert service.is_enabled() is False
    service.set_enabled(True)
    assert service.is_enabled() is True
    assert registry.value == command
    service.set_enabled(False)
    assert service.is_enabled() is False
    assert registry.value is None


def test_service_translates_registry_errors() -> None:
    autostart = _autostart_api()
    service = autostart.AutostartService(
        '"C:\\Apps\\LinguaSpark.exe" --startup',
        MemoryStartupRegistry(fail_writes=True),
    )

    with pytest.raises(autostart.AutostartError, match="开机自启"):
        service.set_enabled(True)


def test_general_settings_reflect_and_save_real_autostart_state(
    qtbot, tmp_path: Path
) -> None:
    autostart = _autostart_api()
    registry = MemoryStartupRegistry('"C:\\Apps\\LinguaSpark.exe" --startup')
    service = autostart.AutostartService("updated command --startup", registry)
    dialog = SettingsDialog(_settings(tmp_path), autostart=service)
    qtbot.addWidget(dialog)

    assert dialog.autostart_checkbox.isChecked()
    dialog.autostart_checkbox.setChecked(False)
    dialog._save_general()

    assert registry.value is None
    assert "已关闭" in dialog.autostart_status.text()


def test_general_settings_restores_real_state_when_registry_write_fails(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    autostart = _autostart_api()
    registry = MemoryStartupRegistry(
        '"C:\\Apps\\LinguaSpark.exe" --startup', fail_writes=True
    )
    service = autostart.AutostartService("updated command --startup", registry)
    dialog = SettingsDialog(_settings(tmp_path), autostart=service)
    qtbot.addWidget(dialog)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    dialog.autostart_checkbox.setChecked(False)
    dialog._save_general()

    assert dialog.autostart_checkbox.isChecked()
    assert warnings and warnings[0][0] == "开机自启设置失败"

