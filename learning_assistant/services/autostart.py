"""Platform boundary for starting LinguaSpark at Windows sign-in."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from learning_assistant.core.paths import project_root


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LinguaSpark"


class AutostartError(RuntimeError):
    """The operating system could not read or update autostart state."""


class StartupRegistry(Protocol):
    def read(self) -> str | None: ...

    def write(self, value: str) -> None: ...

    def delete(self) -> None: ...


class WindowsRunRegistry:
    """Current-user Run key adapter; this never requires administrator rights."""

    @staticmethod
    def _winreg():
        if os.name != "nt":
            raise OSError("Windows startup registration is unavailable")
        import winreg

        return winreg

    def read(self) -> str | None:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
            ) as key:
                value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return None
        return str(value)

    def write(self, value: str) -> None:
        winreg = self._winreg()
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, value)

    def delete(self) -> None:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    return
        except FileNotFoundError:
            return


def build_startup_command(
    executable: Path,
    entrypoint: Path | None = None,
) -> str:
    """Build a Windows-safe command for a packaged or source launch."""
    launcher = Path(executable).resolve()
    arguments: list[str] = []
    if entrypoint is not None:
        pythonw = launcher.with_name("pythonw.exe")
        if launcher.name.casefold() == "python.exe" and pythonw.is_file():
            launcher = pythonw
        arguments.append(str(Path(entrypoint).resolve()))
    return subprocess.list2cmdline([str(launcher), *arguments, "--startup"])


def current_startup_command() -> str:
    entrypoint = None
    if not getattr(sys, "frozen", False):
        entrypoint = project_root() / "main.py"
    return build_startup_command(Path(sys.executable), entrypoint)


class AutostartService:
    """Keep the actual OS registration as the single source of truth."""

    def __init__(
        self,
        command: str | None = None,
        registry: StartupRegistry | None = None,
    ) -> None:
        self.command = command or current_startup_command()
        self.registry = registry or WindowsRunRegistry()

    def is_enabled(self) -> bool:
        try:
            return bool(self.registry.read())
        except OSError as error:
            raise AutostartError(f"无法读取开机自启状态：{error}") from error

    def set_enabled(self, enabled: bool) -> None:
        try:
            if enabled:
                self.registry.write(self.command)
            else:
                self.registry.delete()
        except OSError as error:
            raise AutostartError(f"无法更新开机自启设置：{error}") from error

