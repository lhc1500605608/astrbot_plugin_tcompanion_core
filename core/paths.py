"""Data-directory resolution for the plugin.

Production path comes from AstrBot's ``get_astrbot_plugin_data_path()``.
The import is guarded so the unit tests run without an AstrBot install.
"""

from __future__ import annotations

import os
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_tcompanion_core"

#: Explicit override used by tests / local tooling.
DATA_DIR_ENV = "TCOMPANION_DATA_DIR"

try:  # pragma: no cover - only importable inside the AstrBot runtime
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
except ImportError:  # pragma: no cover
    get_astrbot_plugin_data_path = None  # type: ignore[assignment]


def get_plugin_data_dir() -> Path:
    """Return (and do not create) the plugin's private data directory.

    Resolution order:
    1. ``TCOMPANION_DATA_DIR`` env override (tests / local dev).
    2. AstrBot's ``get_astrbot_plugin_data_path()`` + plugin name.
    3. ``$ASTRBOT_ROOT`` (or CWD) + ``data/plugin_data`` + plugin name.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()

    if get_astrbot_plugin_data_path is not None:
        return Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME

    root = os.environ.get("ASTRBOT_ROOT") or os.getcwd()
    return Path(root) / "data" / "plugin_data" / PLUGIN_NAME


def get_db_path() -> Path:
    """Return the SQLite database path inside the plugin data directory."""
    return get_plugin_data_dir() / "tcompanion_core.sqlite3"
