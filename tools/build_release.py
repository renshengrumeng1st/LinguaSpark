"""Build the fast-starting Windows release layout for LinguaSpark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def release_plan(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Describe a release that starts in place instead of extracting itself."""
    root = project_root.resolve()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "LinguaSpark",
        "--icon",
        str(root / "assets" / "icon.ico"),
        "--add-data",
        f"{root / 'assets'};assets",
    ]
    dictionary = root / "data" / "ecdict_core.sqlite3"
    if dictionary.exists():
        command.extend(["--add-data", f"{dictionary};data"])
    for module in (
        "pythoncom",
        "win32com.client",
        "comtypes.client",
        "comtypes.gen.UIAutomationClient",
    ):
        command.extend(["--hidden-import", module])
    command.append(str(root / "main.py"))
    return {
        "layout": "onedir",
        "executable": str(root / "dist" / "LinguaSpark" / "LinguaSpark.exe"),
        "command": command,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the build plan without invoking PyInstaller",
    )
    args = parser.parse_args(argv)
    plan = release_plan()
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    return subprocess.run(plan["command"], cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())

