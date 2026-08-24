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
import stat
import tempfile
import uuid


_qt_dll_directory = None


def _prepare_icu_runtime(system_icu: Path, runtime_root: Path) -> Path:
    """Copy the current system ICU into a writable, versioned runtime path."""
    source_stat = system_icu.stat()
    version = f"{source_stat.st_size:x}-{source_stat.st_mtime_ns:x}"
    runtime_dir = runtime_root / version
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / "icuuc.dll"
    expected_size = source_stat.st_size

    if target.exists() and target.stat().st_size == expected_size:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
        return target

    temporary = runtime_dir / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copyfile(system_icu, temporary)
        temporary.chmod(stat.S_IREAD | stat.S_IWRITE)
        try:
            os.replace(temporary, target)
        except PermissionError:
            if not target.exists() or target.stat().st_size != expected_size:
                raise
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
        return target
    finally:
        if temporary.exists():
            temporary.unlink()


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
    runtime_root = Path(tempfile.gettempdir()) / "LinguaSpark" / "qt-runtime"
    target = _prepare_icu_runtime(system_icu, runtime_root)
    _qt_dll_directory = os.add_dll_directory(str(target.parent))


_bootstrap_windows_qt()

__version__ = "2.1.0"
