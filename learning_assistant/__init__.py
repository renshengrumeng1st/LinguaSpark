"""AI language learning assistant.

The package is intentionally language-neutral.  English-specific behaviour
lives in providers, so another language can be added without replacing the UI
or orchestration layers.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import tempfile


_qt_dll_directory = None


def _bootstrap_windows_qt() -> None:
    """Expose Windows' system ICU under the name used by Qt wheels.

    Some Windows PySide Essentials wheels link to ``icuuc.dll`` while modern
    Windows ships the same unsuffixed ICU API in ``System32\\icu.dll``.  A
    private runtime copy avoids depending on an incompatible Conda ICU and
    avoids redistributing a Windows system binary with the application.
    """
    global _qt_dll_directory
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    spec = importlib.util.find_spec("PySide6")
    if not spec or not spec.submodule_search_locations:
        return
    package_dir = Path(next(iter(spec.submodule_search_locations)))
    if (package_dir / "icuuc.dll").exists():
        return
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    system_icu = windows_dir / "System32" / "icu.dll"
    if not system_icu.exists():
        return
    runtime_dir = Path(tempfile.gettempdir()) / "LinguaSpark" / "qt-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / "icuuc.dll"
    if not target.exists() or target.stat().st_size != system_icu.stat().st_size:
        shutil.copy2(system_icu, target)
    _qt_dll_directory = os.add_dll_directory(str(runtime_dir))


_bootstrap_windows_qt()

__version__ = "2.0.0"
