"""Relationship stages, affinity-ledger policy, and interaction dynamics.

Pure domain logic (no SQLite): the store applies these rules and the contract
projects them. Frozen thresholds: see ``docs/CONTRACT.md`` §9.

Anti-inflation invariants:
* a single event contributes at most :data:`MAX_EVENT_DELTA` (``+0.03``);
* positive gain per ``(persona_id, user_id)`` per day is capped at
  :data:`DAILY_POSITIVE_CAP` (``+0.10``);
* the ledger is keyed by ``(persona_id, user_id, event_id)`` so replays are
  idempotent;
* idle days decay affinity by :data:`DAILY_DECAY` (``-0.005``) toward 0 and
  never below it.

Group sessions are isolated: they never read or mutate a private
``(persona_id, user_id)`` relationship (see :func:`parse_umo`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

#: Maximum affinity gain contributed by one event.
MAX_EVENT_DELTA = 0.03
#: Maximum positive affinity gain per ``(persona_id, user_id)`` per day.
DAILY_POSITIVE_CAP = 0.10
#: Affinity lost per idle day (converges toward 0, never negative).
DAILY_DECAY = 0.005
#: Downgrade hysteresis: affinity must fall this far below a stage floor.
DOWNGRADE_HYSTERESIS = 0.02

STAGE_STRANGER = "陌生"
STAGE_ACQUAINTED = "眼熟"
STAGE_FAMILIAR = "熟悉"
STAGE_CLOSE = "亲近"
STAGE_INTIMATE = "亲密"
#: Returned when no relationship data exists at all.
STAGE_UNKNOWN = "unknown"

#: Ordered stages and their inclusive lower affinity bounds.
STAGE_ORDER: tuple[str, ...] = (
    STAGE_STRANGER,
    STAGE_ACQUAINTED,
    STAGE_FAMILIAR,
    STAGE_CLOSE,
    STAGE_INTIMATE,
)
STAGE_LOWER_BOUNDS: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8)

#: A bond may only be held while the stage is at/above "亲近".
BOND_STAGES = frozenset({STAGE_CLOSE, STAGE_INTIMATE})


def clamp_affinity(value: float) -> float:
    """Clamp an affinity value into ``[0.0, 1.0]`` (rounded to 6 dp)."""
    return round(min(1.0, max(0.0, float(value))), 6)


def _stage_index(affinity: float) -> int:
    index = 0
    for i, lower in enumerate(STAGE_LOWER_BOUNDS):
        if affinity >= lower:
            index = i
    return index


def stage_for(
    affinity: float,
    previous: str | None = None,
    *,
    hysteresis: float = DOWNGRADE_HYSTERESIS,
) -> str:
    """Map ``affinity`` to a stage, applying downgrade hysteresis.

    Upgrades are immediate once a threshold is crossed. A downgrade only
    happens when ``affinity`` falls ``hysteresis`` below the current stage's
    floor; inside that band the previous stage is held to avoid flapping
    ("降档迟滞 0.02").
    """
    value = clamp_affinity(affinity)
    index = _stage_index(value)
    if previous in STAGE_ORDER:
        previous_index = STAGE_ORDER.index(previous)
        if index < previous_index:
            floor = STAGE_LOWER_BOUNDS[previous_index] - hysteresis
            if value >= floor:
                return previous
    return STAGE_ORDER[index]


def cap_event_delta(delta: float) -> float:
    """Clamp one event's delta: positive gains cap at ``+0.03``.

    Negative events do not deduct affinity in Phase 1 (the emotion ledger is
    Phase 2); they simply do not add.
    """
    if delta <= 0:
        return 0.0
    return min(float(delta), MAX_EVENT_DELTA)


def effective_delta(delta: float, daily_positive_used: float = 0.0) -> float:
    """Apply the per-event cap and the remaining daily positive allowance."""
    stepped = cap_event_delta(delta)
    if stepped <= 0:
        return 0.0
    remaining = max(0.0, DAILY_POSITIVE_CAP - max(0.0, daily_positive_used))
    return round(min(stepped, remaining), 6)


def decayed(affinity: float, days: int, *, rate: float = DAILY_DECAY) -> float:
    """Return affinity after ``days`` idle days, converging toward 0."""
    if days <= 0:
        return clamp_affinity(affinity)
    return clamp_affinity(clamp_affinity(affinity) - rate * days)


def derive_bond(stage: str, has_bond_event: bool, previous: bool = False) -> bool:
    """A bond requires a dedicated event and a stage at/above "亲近"."""
    if stage not in BOND_STAGES:
        return False
    return bool(previous or has_bond_event)


def ignored_decay_factor(streak: int) -> float:
    """Speed multiplier applied while proactive messages go unanswered.

    ``0`` unanswered → ``1.0``; each further miss halves the factor, so a long
    streak visibly slows the persona down without ever fully silencing it.
    """
    return 1.0 / (1.0 + max(0, int(streak)))


@dataclass(frozen=True)
class InteractionDynamics:
    """Aggregated interaction dynamics for one ``(persona_id, user_id)``."""

    unanswered_streak: int = 0
    message_count: int = 0
    proactive_sent: int = 0
    proactive_replied: int = 0
    reply_delay_sum: float = 0.0
    reply_delay_count: int = 0
    last_interaction_at: str | None = None
    pending_proactive_at: str | None = None

    @property
    def avg_reply_delay(self) -> float | None:
        """Mean seconds between a proactive message and the user's reply."""
        if self.reply_delay_count <= 0:
            return None
        return self.reply_delay_sum / self.reply_delay_count

    @property
    def ignored_decay_factor(self) -> float:
        """Current slow-down factor derived from the unanswered streak."""
        return ignored_decay_factor(self.unanswered_streak)

    def to_dict(self) -> dict:
        return {
            "unanswered_streak": self.unanswered_streak,
            "message_count": self.message_count,
            "proactive_sent": self.proactive_sent,
            "proactive_replied": self.proactive_replied,
            "avg_reply_delay": self.avg_reply_delay,
            "ignored_decay_factor": self.ignored_decay_factor,
        }

    @classmethod
    def from_row(cls, row) -> InteractionDynamics:
        if row is None:
            return cls()
        return cls(
            unanswered_streak=int(row["unanswered_streak"] or 0),
            message_count=int(row["message_count"] or 0),
            proactive_sent=int(row["proactive_sent"] or 0),
            proactive_replied=int(row["proactive_replied"] or 0),
            reply_delay_sum=float(row["reply_delay_sum"] or 0.0),
            reply_delay_count=int(row["reply_delay_count"] or 0),
            last_interaction_at=row["last_interaction_at"],
            pending_proactive_at=row["pending_proactive_at"],
        )


@dataclass
class RelationshipState:
    """Persisted relationship row for one ``(persona_id, user_id)`` pair."""

    persona_id: str
    user_id: str
    affinity: float = 0.0
    stage: str = STAGE_STRANGER
    bond: bool = False
    last_active_day: str | None = None
    last_decay_day: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "persona_id": self.persona_id,
            "user_id": self.user_id,
            "affinity": self.affinity,
            "stage": self.stage,
            "bond": self.bond,
            "last_active_day": self.last_active_day,
            "last_decay_day": self.last_decay_day,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row) -> RelationshipState:
        return cls(
            persona_id=row["persona_id"],
            user_id=row["user_id"],
            affinity=float(row["affinity"] or 0.0),
            stage=str(row["stage"] or STAGE_STRANGER),
            bond=bool(row["bond"]),
            last_active_day=row["last_active_day"],
            last_decay_day=row["last_decay_day"],
            updated_at=str(row["updated_at"] or ""),
        )


@dataclass(frozen=True)
class UmoKey:
    """Parsed AstrBot unified-message-origin key.

    Format is ``platform:MessageType:session_id`` (e.g.
    ``aiocqhttp:FriendMessage:67890``). ``is_group`` marks a group session:
    such sessions are isolated from private relationships.
    """

    raw: str
    platform: str
    session_type: str
    session_id: str
    is_group: bool
    user_id: str

    @property
    def isolated(self) -> bool:
        return self.is_group


def parse_umo(umo: str) -> UmoKey:
    """Parse a UMO string into an isolated per-user relationship key."""
    raw = umo or ""
    parts = raw.split(":")
    platform = parts[0] if parts else ""
    if len(parts) >= 3:
        session_type = parts[1]
        session_id = ":".join(parts[2:])
    elif len(parts) == 2:
        session_type, session_id = parts[1], ""
    else:
        session_type, session_id = "", ""
    is_group = "group" in session_type.lower()
    if is_group:
        user_id = f"group:{session_id}"
    else:
        user_id = session_id or raw
    return UmoKey(
        raw=raw,
        platform=platform,
        session_type=session_type,
        session_id=session_id,
        is_group=is_group,
        user_id=user_id,
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def day_of(moment: datetime) -> str:
    return moment.date().isoformat()
