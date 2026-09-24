"""Identity-merge helpers (v1.8).

Pure, side-effect-free helpers plus the ``identity`` config parser. Two things
live here:

* :func:`is_group_key` / the tail helpers that decide which private keys could
  belong to the same person (read-only panel hints);
* :class:`IdentityConfig`, which gates the opt-in automatic merge performed in
  ``ContractV1._private_scope``.

No network, no database access and nothing here ever writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .relationship import parse_umo

#: Reason labels surfaced by the panel. Kept as plain strings so they can travel
#: through JSON without an enum dependency.
SUSPECT_REASON_CANONICAL = "canonical_suffix"
SUSPECT_REASON_SAME_TAIL = "same_tail"

DEFAULT_IDENTITY_AUTO_MIGRATE = False


@dataclass(frozen=True)
class IdentityConfig:
    """Effective ``identity`` group (defaults applied)."""

    auto_migrate: bool = DEFAULT_IDENTITY_AUTO_MIGRATE

    def to_dict(self) -> dict:
        return {"auto_migrate": self.auto_migrate}


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def parse_identity_config(config) -> IdentityConfig:
    """Parse the ``identity`` group (or flat ``auto_migrate``); defaults on miss."""
    if not isinstance(config, dict):
        return IdentityConfig()
    group = config.get("identity")
    if isinstance(group, dict):
        return IdentityConfig(
            auto_migrate=_as_bool(group.get("auto_migrate"), DEFAULT_IDENTITY_AUTO_MIGRATE)
        )
    if "auto_migrate" in config:
        return IdentityConfig(
            auto_migrate=_as_bool(config.get("auto_migrate"), DEFAULT_IDENTITY_AUTO_MIGRATE)
        )
    return IdentityConfig()


def is_group_key(user_id: str) -> bool:
    """True for group scopes stored either as ``group:*`` or as a group UMO."""
    uid = str(user_id or "")
    if not uid:
        return False
    if uid.startswith("group:"):
        return True
    return parse_umo(uid).is_group


def digit_tail(user_id: str) -> str:
    """Return the trailing digit run of a ``prefix:digits`` / bare-digit key.

    Only the canonical (``prefix:tail``) and bare (``tail``) shapes qualify; a
    full UMO such as ``aiocqhttp:FriendMessage:42`` is deliberately excluded so
    session ids never masquerade as person keys. Returns ``""`` otherwise.
    """
    parts = str(user_id or "").split(":")
    if len(parts) == 1:
        tail = parts[0]
    elif len(parts) == 2:
        tail = parts[1]
    else:
        return ""
    tail = tail.strip()
    if tail and tail.isascii() and tail.isdigit():
        return tail
    return ""


def is_canonical_of(candidate: str, other: str) -> bool:
    """True when ``candidate`` looks like ``prefix:other`` (canonical tail)."""
    parts = str(candidate or "").split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    return parts[1] == str(other or "")
