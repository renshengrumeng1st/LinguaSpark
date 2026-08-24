from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_release_plan_uses_fast_installed_layout_and_project_icon() -> None:
    """Reintroducing an extract-on-launch executable must fail this test."""
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "tools/build_release.py", "--dry-run"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    command = plan["command"]
    assert plan["layout"] == "onedir"
    assert plan["executable"] == str(
        project_root / "dist" / "LinguaSpark" / "LinguaSpark.exe"
    )
    assert "--onedir" in command
    assert "--onefile" not in command
    assert command[command.index("--icon") + 1] == str(
        project_root / "assets" / "icon.ico"
    )

