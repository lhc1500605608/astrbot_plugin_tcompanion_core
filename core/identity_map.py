"""Read-only consumer of the shared ``identity_map.json`` (v1.9).

The memory plugin (tmemory) is the identity authority: it exports a single
shared file ``<plugin_data>/_shared/identity_map.json`` mapping
``(adapter, adapter_user_id) -> canonical_user_id`` (see ``docs/CONTRACT.md``
§20 and the frozen plan TMEAAA-568 §2). companion-core never writes it.

This module parses that file and answers ``lookup(adapter, adapter_user_id)``.
It is the **offline / standalone fallback** used by ``MemoryBridge`` when the
online identity bridge is unavailable, so the same Person resolves across
adapters even without tmemory running.

Invariants:

* **Fail-closed**: a missing, unreadable, malformed or wrong-version file all
  collapse to an empty index — ``lookup`` returns ``None`` and never raises.
* **Read-only**: the file is opened for reading only; nothing is written back.
* **Key normalization**: the lookup key is the authority's
  ``(adapter, adapter_user_id)`` pair. Callers pass the UMO ``session_id`` from
  ``parse_umo``; known platform encodings (WebChat ``webchat!<user>!<conv>``) are
  decoded back to the sender id so both sides agree (v1.9, TMEAAA-578).
* **Cached by mtime**: the parsed index is reused until the file's mtime
  changes (``st_mtime_ns``), so a burst of messages does not re-read the file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .paths import get_shared_data_dir

logger = logging.getLogger(__name__)

#: File name (inside the shared data directory).
IDENTITY_MAP_FILENAME = "identity_map.json"

#: Only this format version is understood; anything else is ignored (fail-closed).
IDENTITY_MAP_VERSION = 1

#: Authority expected in the payload (informational, not enforced).
IDENTITY_MAP_AUTHORITY = "tmemory"

#: WebChat encodes its private ``session_id`` as ``webchat!<user>!<conversation>``.
_WEBCHAT_PREFIX = "webchat!"


def normalize_adapter_user_id(platform: str, adapter_user_id: str) -> str:
    """Decode a UMO ``session_id`` into the authority's ``adapter_user_id``.

    The authority (tmemory) keys bindings by ``event.get_sender_id()``. For most
    adapters the UMO ``session_id`` already equals the sender id, but the WebChat
    adapter encodes it as ``webchat!<username>!<conversation>``
    (``webchat_adapter.py``). Decode back to ``<username>`` so both sides land on
    the same key. Unknown forms are returned unchanged (v1.9, TMEAAA-578).
    """
    user = str(adapter_user_id or "").strip()
    if str(platform or "").strip() == "webchat" and user.startswith(_WEBCHAT_PREFIX):
        parts = user.split("!", 2)
        if len(parts) == 3 and parts[1].strip():
            return parts[1].strip()
    return user


def resolve_identity_map_path(path: Path | str | None = None) -> Path:
    """Return the shared map path, or the explicit ``path`` when given."""
    if path is not None:
        return Path(path)
    return get_shared_data_dir() / IDENTITY_MAP_FILENAME


class IdentityMap:
    """Read-only, mtime-cached view of the shared identity map.

    ``path`` defaults to the shared file; tests inject a temp file. All errors
    fail closed to an empty index.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = resolve_identity_map_path(path)
        self._loaded = False
        self._mtime_ns: int | None = None
        self._index: dict[str, str] = {}

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        """(Re)read the file when it changed; corrupt/missing → empty index."""
        try:
            mtime_ns = self._path.stat().st_mtime_ns
        except OSError:
            self._index = {}
            self._mtime_ns = None
            self._loaded = True
            return

        if self._loaded and self._mtime_ns == mtime_ns:
            return

        index: dict[str, str] = {}
        try:
            with self._path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception:  # noqa: BLE001 - read path must never raise
            payload = None

        if isinstance(payload, dict) and payload.get("version") == IDENTITY_MAP_VERSION:
            raw = payload.get("index")
            if isinstance(raw, dict):
                for key, value in raw.items():
                    name = str(key or "").strip()
                    canonical = str(value or "").strip()
                    if name and canonical:
                        index[name] = canonical

        self._index = index
        self._mtime_ns = mtime_ns
        self._loaded = True

    def lookup(self, adapter: str, adapter_user_id: str) -> str | None:
        """Return the canonical ``person_id`` for one binding, else ``None``.

        ``adapter_user_id`` may be a UMO ``session_id`` (as produced by
        ``parse_umo``): known encodings are normalized via
        :func:`normalize_adapter_user_id` before the exact-key lookup, so the
        WebChat encoded session hits the authority's ``<username>`` key.
        """
        name = str(adapter or "").strip()
        user = normalize_adapter_user_id(name, adapter_user_id)
        if not name or not user:
            return None
        self._load()
        return self._index.get(f"{name}:{user}") or None

    def size(self) -> int:
        """Number of indexed bindings (read-only, for observability/tests)."""
        self._load()
        return len(self._index)
