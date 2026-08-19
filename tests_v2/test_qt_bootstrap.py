from __future__ import annotations

import os
from pathlib import Path
import stat

import learning_assistant


def _make_writable(path: Path) -> None:
    if path.exists():
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_prepare_icu_runtime_keeps_windows_updates_away_from_readonly_target(
    tmp_path: Path,
) -> None:
    """Changing the system ICU must not overwrite an old read-only runtime DLL."""
    prepare = getattr(learning_assistant, "_prepare_icu_runtime", None)
    assert callable(prepare), "ICU runtime preparation helper is missing"

    system_icu = tmp_path / "icu.dll"
    runtime_root = tmp_path / "qt-runtime"
    system_icu.write_bytes(b"windows-icu-v1")
    system_icu.chmod(stat.S_IREAD)
    first: Path | None = None
    second: Path | None = None
    try:
        first = prepare(system_icu, runtime_root)
        assert first.name == "icuuc.dll"
        assert first.read_bytes() == b"windows-icu-v1"
        assert first.stat().st_mode & stat.S_IWRITE

        first.chmod(stat.S_IREAD)
        _make_writable(system_icu)
        system_icu.write_bytes(b"windows-icu-v2-with-new-size")
        os.utime(system_icu, None)
        system_icu.chmod(stat.S_IREAD)

        second = prepare(system_icu, runtime_root)
        assert second != first
        assert second.read_bytes() == b"windows-icu-v2-with-new-size"
        assert second.stat().st_mode & stat.S_IWRITE
        assert first.read_bytes() == b"windows-icu-v1"
    finally:
        _make_writable(system_icu)
        if first is not None:
            _make_writable(first)
        if second is not None:
            _make_writable(second)


def test_prepare_icu_runtime_accepts_a_valid_concurrent_winner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A second process winning the publish race must not break startup."""
    system_icu = tmp_path / "icu.dll"
    runtime_root = tmp_path / "qt-runtime"
    system_icu.write_bytes(b"shared-windows-icu")

    def lose_publish_race(temporary: str | Path, target: str | Path) -> None:
        Path(target).write_bytes(system_icu.read_bytes())
        raise PermissionError("target is already loaded by another process")

    monkeypatch.setattr(learning_assistant.os, "replace", lose_publish_race)
    target = learning_assistant._prepare_icu_runtime(system_icu, runtime_root)

    assert target.read_bytes() == b"shared-windows-icu"
    assert sorted(path.name for path in target.parent.iterdir()) == ["icuuc.dll"]
