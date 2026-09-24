"""Data-directory resolution for the plugin.

Production path comes from AstrBot's ``get_astrbot_plugin_data_path()``.
The import is guarded so the unit tests run without an AstrBot install.
"""

from __future__ import annotations

import os
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_tcompanion_core"

#: Cross-plugin shared data directory (sibling of the per-plugin dirs).
SHARED_DIR_NAME = "_shared"

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


def get_shared_data_dir() -> Path:
    """Return (and do not create) the cross-plugin shared data directory.

    ``<plugin_data>/_shared`` — a sibling of the per-plugin directories, so
    tmemory (writer, ``get_astrbot_plugin_data_path()``) and companion-core
    (reader) resolve the same file on the same machine. ``TCOMPANION_DATA_DIR``
    relocates the whole tree for tests.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser() / SHARED_DIR_NAME

    if get_astrbot_plugin_data_path is not None:
        return Path(get_astrbot_plugin_data_path()) / SHARED_DIR_NAME

    root = os.environ.get("ASTRBOT_ROOT") or os.getcwd()
    return Path(root) / "data" / "plugin_data" / SHARED_DIR_NAME


def get_db_path() -> Path:
    """Return the SQLite database path inside the plugin data directory."""
    return get_plugin_data_dir() / "tcompanion_core.sqlite3"


def get_identity_mirror_path() -> Path:
    """Return companion's private mirror of the shared identity map.

    ``<plugin_data>/astrbot_plugin_tcompanion_core/identity_map.json`` — the
    single writer is companion itself (v1.10, TMEAAA-574).
    """
    return get_plugin_data_dir() / "identity_map.json"
