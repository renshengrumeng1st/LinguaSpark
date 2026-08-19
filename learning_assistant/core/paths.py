"""All mutable data lives outside the installation directory."""

from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "LinguaSpark"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    # QStandardPaths.AppDataLocation changes depending on whether QApplication
    # already has its organization/application names. Keep one stable location
    # for CLI migrations, tests, the packaged app, and normal desktop startup.
    if os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / APP_NAME
    else:
        path = Path.home() / ".linguaspark"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_dictionary_path() -> Path:
    return project_root() / "data" / "ecdict_core.sqlite3"
