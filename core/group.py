"""Group understanding: bounded group/member aggregates + advisory gate.

Pure domain logic (no SQLite): the store persists bounded counts and the
contract projects them. This module owns the group config, the member-key
scheme and the deterministic participation gate (see ``docs/CONTRACT.md`` §17).

Privacy invariants (mirrored by the store):

* **No message bodies**: only counts, timestamps and one sanitized short label
  (``sanitize_thread_title``) are ever stored.
* **Group members are local**: a member key is ``group:<session>#<member>`` so a
  member is never merged with a private ``person`` and never aggregated across
  groups.
* **Deterministic**: the same stored state + ``now`` always yields the same
  gate decision.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .motivation import sanitize_thread_title

# -- participation reason codes (fixed / observable) -----------------------
REASON_OK = "ok"
REASON_COOLDOWN = "cooldown"
REASON_HOURLY_LIMIT = "hourly_limit"
REASON_GROUP_BUSY = "group_busy"
REASON_DISABLED = "disabled"

#: Reasons surfaced for an *enabled* gate (a disabled section reports
#: :data:`REASON_DISABLED` and never participates).
GATE_REASONS: tuple[str, ...] = (
    REASON_OK,
    REASON_COOLDOWN,
    REASON_HOURLY_LIMIT,
    REASON_GROUP_BUSY,
)

# -- defaults --------------------------------------------------------------
GROUP_MIN_REPLY_GAP_SEC = 90
GROUP_HOURLY_LIMIT = 6
GROUP_BUSY_THRESHOLD = 120
#: Longest member id accepted into a member key (bounded, never raw text).
GROUP_MEMBER_KEY_MAX = 64
#: Hard ceiling on a stored per-member familiarity counter (bounded growth).
GROUP_MEMBER_FAMILIARITY_MAX = 100000

#: Activity-level buckets, relative to ``busy_group_threshold`` messages/hour.
ACTIVITY_LOW = "low"
ACTIVITY_MEDIUM = "medium"
ACTIVITY_HIGH = "high"


@dataclass(frozen=True)
class GroupConfig:
    """Effective ``group`` config group (coerced + defaulted)."""

    enabled: bool = True
    participation_enabled: bool = True
    min_reply_gap_sec: int = GROUP_MIN_REPLY_GAP_SEC
    hourly_limit: int = GROUP_HOURLY_LIMIT
    busy_group_threshold: int = GROUP_BUSY_THRESHOLD
    member_tracking_enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _cfg_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cfg_int(value, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def parse_group_config(config) -> GroupConfig:
    """Read the ``group`` group; defaults on any missing/malformed value.

    Parsed fresh on each call because AstrBot hot-reload mutates the injected
    config mapping in place.
    """
    section: dict = {}
    if isinstance(config, dict):
        raw = config.get("group")
        if isinstance(raw, dict):
            section = raw
    return GroupConfig(
        enabled=_cfg_bool(section.get("enabled"), True),
        participation_enabled=_cfg_bool(section.get("participation_enabled"), True),
        min_reply_gap_sec=_cfg_int(section.get("min_reply_gap_sec"), GROUP_MIN_REPLY_GAP_SEC),
        hourly_limit=_cfg_int(section.get("hourly_limit"), GROUP_HOURLY_LIMIT),
        busy_group_threshold=_cfg_int(
            section.get("busy_group_threshold"), GROUP_BUSY_THRESHOLD
        ),
        member_tracking_enabled=_cfg_bool(section.get("member_tracking_enabled"), True),
    )


def member_key_for(session_key: str, member_id: str | None) -> str:
    """Build the local group-member key ``group:<session>#<member>``.

    ``session_key`` is the parsed UMO group key (``group:<session>``). An empty
    ``member_id`` yields the empty string (no member context). The member id is
    clipped so a caller can never smuggle long raw text through this path.
    """
    cleaned = sanitize_thread_title(member_id or "", max_len=GROUP_MEMBER_KEY_MAX)
    if not cleaned or not session_key:
        return ""
    return f"{session_key}#{cleaned}"


def clamp_familiarity(value) -> int:
    """Clamp a stored familiarity counter into ``[0, MAX]``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(GROUP_MEMBER_FAMILIARITY_MAX, number))


def activity_level(hour_count: int, busy_threshold: int = GROUP_BUSY_THRESHOLD) -> str:
    """Bucket messages-per-hour into ``low`` / ``medium`` / ``high``."""
    threshold = max(1, int(busy_threshold or GROUP_BUSY_THRESHOLD))
    count = max(0, int(hour_count or 0))
    if count >= threshold:
        return ACTIVITY_HIGH
    if count * 3 >= threshold:
        return ACTIVITY_MEDIUM
    return ACTIVITY_LOW


def _parse_iso(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def evaluate_participation(
    *,
    now: datetime,
    cfg: GroupConfig,
    last_participation_ts: str | None = None,
    participation_hour_count: int = 0,
    activity_hour_count: int = 0,
) -> dict:
    """Return the advisory participation gate ``{allow, reason, ...}``.

    Gate order is stable and observable: ``cooldown`` → ``hourly_limit`` →
    ``group_busy`` → ``ok``. When the section (or participation) is disabled the
    result is a non-participating ``disabled`` block. The timestamps are pure
    inputs; the caller decides whether to stamp a granted slot.
    """
    moment = _now(now)
    limit = max(0, int(cfg.hourly_limit))
    busy = max(1, int(cfg.busy_group_threshold or GROUP_BUSY_THRESHOLD))
    used_hour = max(0, int(participation_hour_count or 0))
    hourly_remaining = max(0, limit - used_hour)

    if not cfg.enabled or not cfg.participation_enabled:
        return {
            "allow": False,
            "reason": REASON_DISABLED,
            "cooldown_remaining_sec": 0,
            "hourly_remaining": hourly_remaining,
        }

    gap = max(0, int(cfg.min_reply_gap_sec))
    last = _parse_iso(last_participation_ts)
    if gap > 0 and last is not None:
        elapsed = (moment - last).total_seconds()
        if elapsed < gap:
            return {
                "allow": False,
                "reason": REASON_COOLDOWN,
                "cooldown_remaining_sec": int(math.ceil(gap - max(0.0, elapsed))),
                "hourly_remaining": hourly_remaining,
            }

    if used_hour >= limit:
        return {
            "allow": False,
            "reason": REASON_HOURLY_LIMIT,
            "cooldown_remaining_sec": 0,
            "hourly_remaining": 0,
        }

    if max(0, int(activity_hour_count or 0)) >= busy:
        return {
            "allow": False,
            "reason": REASON_GROUP_BUSY,
            "cooldown_remaining_sec": 0,
            "hourly_remaining": hourly_remaining,
        }

    return {
        "allow": True,
        "reason": REASON_OK,
        "cooldown_remaining_sec": 0,
        "hourly_remaining": hourly_remaining,
    }


def topic_age_min(topic_ts: str | None, now: datetime) -> float | None:
    """Minutes since the topic label was last refreshed (``None`` if unknown)."""
    parsed = _parse_iso(topic_ts)
    if parsed is None:
        return None
    age = (_now(now) - parsed).total_seconds() / 60.0
    if age < 0:
        return None
    return round(age, 1)
