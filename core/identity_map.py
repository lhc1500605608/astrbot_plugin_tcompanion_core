"""Read-only consumer of the shared ``identity_map.json`` (v1.9, mirror v1.10).

The memory plugin (tmemory) is the identity authority: it exports a single
shared file ``<plugin_data>/_shared/identity_map.json`` mapping
``(adapter, adapter_user_id) -> canonical_user_id`` (see ``docs/CONTRACT.md``
§20/§21 and the frozen plan TMEAAA-568 §2). companion-core never writes that
file.

This module parses the map and answers two read-only questions:

* :meth:`IdentityMap.lookup` — ``(adapter, adapter_user_id) -> canonical`` for a
  live UMO (the offline fallback used by ``MemoryBridge.resolve_person``);
* :meth:`IdentityMap.resolve_key` — a stored private key (as kept by the store)
  ``-> canonical``, used by the panel to group relationships (v1.10). The
  mapping is authoritative; an unmatched key is **not** guessed.

**Local mirror (v1.10, TMEAAA-574)**: companion keeps its own copy at
``<plugin_data>/astrbot_plugin_tcompanion_core/identity_map.json`` (single
writer = companion). When the shared file is readable its content is mirrored;
when it is unavailable/missing/corrupt the mirror is read instead, so companion
stays runnable and can still rekey ``(adapter, adapter_user_id) -> canonical``
on its own.

Invariants:

* **Fail-closed**: a missing, unreadable, malformed or wrong-version file all
  collapse to an empty index — lookups return ``None`` and never raise.
* **Read-only for the shared file**: it is opened for reading only. The only
  write is companion's own private mirror, done atomically and best-effort.
* **Key normalization**: known platform encodings (WebChat
  ``webchat!<user>!<conv>``) are decoded back to the sender id so both sides
  agree (v1.9, TMEAAA-578).
* **Cached by mtime**: the parsed index is reused until either file's mtime
  changes (``st_mtime_ns``), so a burst of messages does not re-read them.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .paths import get_identity_mirror_path, get_shared_data_dir

logger = logging.getLogger(__name__)

#: File name (inside the shared data directory and the private data directory).
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


def resolve_mirror_path(path: Path | str | None = None) -> Path:
    """Return companion's private mirror path, or the explicit ``path``."""
    if path is not None:
        return Path(path)
    return get_identity_mirror_path()


class IdentityMap:
    """Read-only, mtime-cached view of the shared identity map + local mirror.

    ``path`` defaults to the shared file, ``mirror_path`` to companion's private
    copy. Tests inject temp files; when ``path`` is injected and no explicit
    ``mirror_path`` is given the mirror is disabled (no writes).
    """

    def __init__(
        self,
        path: Path | str | None = None,
        mirror_path: Path | str | None = None,
    ) -> None:
        self._path = resolve_identity_map_path(path)
        if mirror_path is not None:
            self._mirror_path: Path | None = Path(mirror_path)
        elif path is None:
            self._mirror_path = resolve_mirror_path()
        else:
            # An explicitly injected shared path keeps tests side-effect free.
            self._mirror_path = None
        self._loaded = False
        self._signature: tuple[int | None, int | None] | None = None
        self._index: dict[str, str] = {}
        self._aliases: dict[str, str] = {}
        self._entries: list[tuple[str, str, str]] = []

    @property
    def path(self) -> Path:
        return self._path

    @property
    def mirror_path(self) -> Path | None:
        return self._mirror_path

    # -- loading ------------------------------------------------------------
    def _stat_ns(self, path: Path | None) -> int | None:
        if path is None:
            return None
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    @staticmethod
    def _read_payload(path: Path) -> object | None:
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        except Exception:  # noqa: BLE001 - read path must never raise
            return None

    @staticmethod
    def _is_valid(payload: object) -> bool:
        return isinstance(payload, dict) and payload.get("version") == IDENTITY_MAP_VERSION

    def _sync_mirror(self, payload: dict) -> None:
        """Best-effort atomic copy of a valid shared payload into the mirror."""
        mirror = self._mirror_path
        if mirror is None:
            return
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if mirror.exists() and mirror.read_text(encoding="utf-8") == encoded:
                return
            mirror.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(mirror.parent),
                prefix=".identity_map.",
                suffix=".tmp",
                delete=False,
            )
            try:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, mirror)
        except Exception:  # noqa: BLE001 - mirroring must never raise
            logger.debug("tcompanion_core: identity map mirror sync skipped", exc_info=True)

    def _build(
        self, payload: dict
    ) -> tuple[dict[str, str], dict[str, str], list[tuple[str, str, str]]]:
        """Return ``(index, aliases, entries)`` from a validated payload.

        ``aliases`` maps both ``adapter:uid`` and the bare ``uid`` (plus every
        canonical itself) to its canonical, so a stored key can be resolved with
        one dict lookup. ``entries`` keeps the parsed triples for the slower
        encoded-session fallback in :meth:`resolve_key`.
        """
        index: dict[str, str] = {}
        raw_index = payload.get("index")
        if isinstance(raw_index, dict):
            for key, value in raw_index.items():
                name = str(key or "").strip()
                canonical = str(value or "").strip()
                if name and canonical:
                    index[name] = canonical
        aliases: dict[str, str] = {}
        entries: list[tuple[str, str, str]] = []
        canonicals: set[str] = set()
        raw_persons = payload.get("persons")
        if isinstance(raw_persons, dict):
            for pid in raw_persons:
                pid = str(pid or "").strip()
                if pid:
                    canonicals.add(pid)
        for name in sorted(index):
            canonical = index[name]
            canonicals.add(canonical)
            aliases.setdefault(name, canonical)
            if ":" in name:
                platform, uid = name.split(":", 1)
                if uid:
                    aliases.setdefault(uid, canonical)
                    entries.append((platform, uid, canonical))
            else:
                entries.append(("", name, canonical))
        for canonical in sorted(canonicals):
            aliases.setdefault(canonical, canonical)
        return index, aliases, entries

    def _load(self) -> None:
        """(Re)read the shared file (then the mirror); corrupt/missing → empty."""
        shared_mtime = self._stat_ns(self._path)
        mirror_mtime = self._stat_ns(self._mirror_path)
        signature = (shared_mtime, mirror_mtime)
        if self._loaded and self._signature == signature:
            return

        payload: object | None = None
        if shared_mtime is not None:
            candidate = self._read_payload(self._path)
            if self._is_valid(candidate):
                payload = candidate
                self._sync_mirror(candidate)
        if payload is None and mirror_mtime is not None:
            candidate = self._read_payload(self._mirror_path)
            if self._is_valid(candidate):
                payload = candidate

        if isinstance(payload, dict):
            self._index, self._aliases, self._entries = self._build(payload)
        else:
            self._index, self._aliases, self._entries = {}, {}, []
        self._signature = (shared_mtime, self._stat_ns(self._mirror_path))
        self._loaded = True

    # -- lookups ------------------------------------------------------------
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

    def resolve_key(self, user_id: str) -> str | None:
        """Map a stored private key to its canonical Person, else ``None``.

        Consulted by the panel: the key may be an index key (``adapter:uid``), a
        bare sender id, an encoded WebChat session id, or already canonical. The
        mapping is authoritative, so an unmatched key returns ``None`` (the
        caller then keeps the key itself, v1.4 behaviour). Group keys never map.
        """
        key = str(user_id or "").strip()
        if not key or key.startswith("group:"):
            return None
        self._load()
        hit = self._aliases.get(key)
        if hit:
            return hit
        for platform, uid, canonical in self._entries:
            if platform and normalize_adapter_user_id(platform, key) == uid:
                return canonical
        return None

    def size(self) -> int:
        """Number of indexed bindings (read-only, for observability/tests)."""
        self._load()
        return len(self._index)
