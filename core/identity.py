"""Identity helpers (v1.10).

Pure, side-effect-free helpers plus the ``identity`` config parser. Identity is
**map-driven**: the canonical Person for a private key comes from the shared
``identity_map.json`` (see :mod:`core.identity_map`), never from string
heuristics. What lives here is therefore only:

* :func:`is_group_key`, the group-scope guard used by the panel/store; and
* :class:`IdentityConfig`, which gates the opt-in automatic rekey performed in
  ``ContractV1._private_scope``.

No network, no database access and nothing here ever writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .relationship import parse_umo

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
