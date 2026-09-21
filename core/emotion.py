"""Phase 2 emotion-event ledger + expression decision (pure domain logic).

Zero-LLM, deterministic and bounded. The kanjyou layer detects events and
reports them through ``ContractV1.record_emotion_event``; this module owns the
scoring rules and the seven-tier expression decision.

Invariants (see ``docs/CONTRACT.md`` §11):

* **No message bodies**: an event carries only a type, a delta and a dedupe
  key — never raw text.
* **Group isolation**: group scopes never record or read private emotion, and
  their expression mode is restricted to the non-intimate group set.
* **Bounded**: per-event delta is clamped to ``±0.03``; valence decays with a
  24h half-life over a 72h window and is clamped to ``[-1, 1]``.
* **Never inflating**: the affinity ledger side of an event is capped by the
  daily positive/negative allowances (``relationship.effective_delta`` +
  :data:`EMOTION_DAILY_NEGATIVE_CAP`) and affinity never drops below ``0.0``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from .relationship import STAGE_ORDER, STAGE_STRANGER, effective_delta

# -- event types ------------------------------------------------------------
EVENT_VALUED_REPLY = "valued_reply"
EVENT_IGNORED_PROACTIVE = "ignored_proactive"
EVENT_GRATITUDE = "gratitude"
EVENT_MISUNDERSTOOD = "misunderstood"
EVENT_SUDDEN_WARMTH = "sudden_warmth"
EVENT_COLD_SHOULDER = "cold_shoulder"

#: Canonical per-event delta (plan §2.1). Unknown types are rejected upstream.
EVENT_DELTAS: dict[str, float] = {
    EVENT_VALUED_REPLY: 0.03,
    EVENT_IGNORED_PROACTIVE: -0.02,
    EVENT_GRATITUDE: 0.02,
    EVENT_MISUNDERSTOOD: -0.03,
    EVENT_SUDDEN_WARMTH: 0.02,
    EVENT_COLD_SHOULDER: -0.01,
}

#: Valid event types, accepted by ``record_emotion_event``.
EVENT_TYPES: tuple[str, ...] = tuple(EVENT_DELTAS)
POSITIVE_EVENT_TYPES = frozenset(t for t, d in EVENT_DELTAS.items() if d > 0)
NEGATIVE_EVENT_TYPES = frozenset(t for t, d in EVENT_DELTAS.items() if d < 0)

#: Hard per-event delta bound (both signs).
MAX_EMOTION_EVENT_DELTA = 0.03
#: Daily *negative* affinity budget (positive uses ``DAILY_POSITIVE_CAP``).
EMOTION_DAILY_NEGATIVE_CAP = 0.06
#: Valence window and half-life.
VALENCE_WINDOW_HOURS = 72
VALENCE_HALF_LIFE_HOURS = 24.0
#: How many recent events are echoed by ``get_emotion_context``.
RECENT_EVENT_LIMIT = 5

# -- emotion states (plan §2.3) --------------------------------------------
STATE_HURT = "受伤"
STATE_AVOID = "回避"
STATE_EXPECT = "期待"
STATE_HAPPY = "开心"
STATE_CALM = "平静"

EMOTION_STATES: tuple[str, ...] = (STATE_HURT, STATE_AVOID, STATE_EXPECT, STATE_HAPPY, STATE_CALM)

# -- expression modes (plan §3) --------------------------------------------
MODE_AVOID = "回避"
MODE_HURT = "受伤"
MODE_RELAXED = "放松"
MODE_LIVELY = "活泼"
MODE_WARM = "温暖"
MODE_CLOSE = "亲近"
MODE_LOVE = "爱意"

EXPRESSION_MODES: tuple[str, ...] = (
    MODE_AVOID,
    MODE_HURT,
    MODE_RELAXED,
    MODE_LIVELY,
    MODE_WARM,
    MODE_CLOSE,
    MODE_LOVE,
)

#: Group sessions may only use these non-intimate modes (plan §3.2).
GROUP_ALLOWED_MODES = frozenset({MODE_RELAXED, MODE_LIVELY, MODE_WARM})
#: Hard warmth ceiling inside a group session.
GROUP_WARMTH_CAP = 0.55

#: Default style hints per mode (plan §3.3); overridable by config upstream.
STYLE_HINTS: dict[str, dict[str, float | str]] = {
    MODE_AVOID: {
        "tone": "简短克制",
        "warmth": 0.25,
        "length_bias": -0.50,
        "proactive_bias": -0.60,
    },
    MODE_HURT: {
        "tone": "低落含蓄",
        "warmth": 0.30,
        "length_bias": -0.30,
        "proactive_bias": -0.40,
    },
    MODE_RELAXED: {
        "tone": "平和自然",
        "warmth": 0.45,
        "length_bias": 0.00,
        "proactive_bias": 0.00,
    },
    MODE_LIVELY: {
        "tone": "轻快俏皮",
        "warmth": 0.55,
        "length_bias": 0.10,
        "proactive_bias": 0.10,
    },
    MODE_WARM: {
        "tone": "柔和体贴",
        "warmth": 0.70,
        "length_bias": 0.05,
        "proactive_bias": 0.05,
    },
    MODE_CLOSE: {
        "tone": "亲昵自然",
        "warmth": 0.80,
        "length_bias": 0.10,
        "proactive_bias": 0.15,
    },
    MODE_LOVE: {
        "tone": "深情温柔",
        "warmth": 0.95,
        "length_bias": 0.05,
        "proactive_bias": 0.20,
    },
}

#: Emotion states that dampen proactive outreach (never boost it).
DAMPING_STATES: dict[str, float] = {STATE_HURT: 0.5, STATE_AVOID: 0.6}

_STAGE_FAMILIAR = "熟悉"


# -- helpers ---------------------------------------------------------------
def _get(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def clamp_valence(value: float) -> float:
    """Clamp valence into ``[-1, 1]`` rounded to 4 dp."""
    return round(clamp(value, -1.0, 1.0), 4)


def cap_emotion_delta(delta: float) -> float:
    """Clamp one emotion event's delta into ``[-0.03, +0.03]``."""
    return round(clamp(delta, -MAX_EMOTION_EVENT_DELTA, MAX_EMOTION_EVENT_DELTA), 6)


def event_delta(event_type: str) -> float:
    """Canonical delta for ``event_type``; ``0.0`` for unknown types."""
    return EVENT_DELTAS.get(event_type, 0.0)


def is_positive(event_type: str) -> bool:
    return event_type in POSITIVE_EVENT_TYPES


def _age_hours(row, now: datetime) -> float | None:
    ts = _parse_ts(_get(row, "ts"))
    if ts is None:
        return None
    return (now - ts).total_seconds() / 3600.0


def compute_valence(events: Sequence, now: datetime | None = None) -> float:
    """Weighted sum of event deltas over the 72h window, clamped to ``[-1, 1]``.

    Weight is ``0.5 ** (age_hours / 24)`` — a 24h half-life. Events older than
    the window (or stamped in the future) are ignored.
    """
    moment = _now(now)
    total = 0.0
    for row in events or ():
        age = _age_hours(row, moment)
        if age is None or age < 0 or age > VALENCE_WINDOW_HOURS:
            continue
        delta = cap_emotion_delta(float(_get(row, "delta", 0.0) or 0.0))
        total += delta * (0.5 ** (age / VALENCE_HALF_LIFE_HOURS))
    return clamp_valence(total)


def recent_events(events: Sequence, limit: int = RECENT_EVENT_LIMIT) -> list[dict]:
    """Return the newest ``limit`` events as ``{event_type, delta, ts}``.

    Only derived values are exposed — never a message body.
    """
    ordered = sorted(
        events or (),
        key=lambda row: (
            _parse_ts(_get(row, "ts")) or datetime.min.replace(tzinfo=timezone.utc),
            str(_get(row, "dedupe_key", "") or ""),
        ),
        reverse=True,
    )
    return [
        {
            "event_type": str(_get(row, "event_type", "") or ""),
            "delta": round(float(_get(row, "delta", 0.0) or 0.0), 6),
            "ts": str(_get(row, "ts", "") or ""),
        }
        for row in ordered[: max(0, int(limit))]
    ]


def emotion_state(
    events: Sequence,
    *,
    now: datetime | None = None,
    unanswered_streak: int = 0,
) -> str:
    """Priority-first emotion state (plan §2.3). Deterministic and bounded."""
    moment = _now(now)
    valence = compute_valence(events, moment)
    streak = max(0, int(unanswered_streak))

    recent_12: list[str] = []
    recent_48: list[str] = []
    for row in events or ():
        age = _age_hours(row, moment)
        if age is None or age < 0:
            continue
        if age <= 12:
            recent_12.append(str(_get(row, "event_type", "") or ""))
        if age <= 48:
            recent_48.append(str(_get(row, "event_type", "") or ""))

    if EVENT_MISUNDERSTOOD in recent_12 or valence <= -0.35:
        return STATE_HURT
    ignored_48 = sum(1 for t in recent_48 if t == EVENT_IGNORED_PROACTIVE)
    if streak >= 2 or ignored_48 >= 2 or valence <= -0.15:
        return STATE_AVOID
    positives_12 = sum(1 for t in recent_12 if t in POSITIVE_EVENT_TYPES)
    if positives_12 >= 1 and valence >= 0.15:
        return STATE_EXPECT
    if valence >= 0.25:
        return STATE_HAPPY
    return STATE_CALM


def emotion_snapshot(
    events: Sequence,
    *,
    now: datetime | None = None,
    unanswered_streak: int = 0,
) -> dict:
    """Full derived emotion view: state/valence/recent/last_event/as_of."""
    moment = _now(now)
    recent = recent_events(events)
    return {
        "state": emotion_state(events, now=moment, unanswered_streak=unanswered_streak),
        "valence": compute_valence(events, moment),
        "recent": recent,
        "last_event": recent[0]["event_type"] if recent else None,
        "as_of": moment.isoformat(),
    }


# -- expression -------------------------------------------------------------
def _stage_index(stage: str) -> int:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0


def style_hints(mode: str) -> dict:
    """Return a copy of the style-hint table row for ``mode``."""
    return dict(STYLE_HINTS.get(mode, STYLE_HINTS[MODE_RELAXED]))


def expression_for(
    *,
    state: str = STATE_CALM,
    valence: float = 0.0,
    stage: str = STAGE_STRANGER,
    bond: bool = False,
    energy: float = 0.0,
    unanswered_streak: int = 0,
    is_group: bool = False,
) -> dict:
    """Decide the seven-tier expression mode (plan §3, priority-first).

    Group sessions are hard-suppressed to ``放松``/``活泼``/``温暖`` and their
    warmth is capped at :data:`GROUP_WARMTH_CAP`, whatever the private inputs.
    """
    value = clamp_valence(valence)
    streak = max(0, int(unanswered_streak))

    if state == STATE_AVOID or streak >= 2:
        mode = MODE_AVOID
        reason = f"连续 {streak} 次主动未回应，档位→回避" if streak >= 2 else "情绪回避，档位→回避"
    elif state == STATE_HURT:
        mode = MODE_HURT
        reason = "近期出现受挫/误解事件，档位→受伤"
    elif bond and stage == "亲密" and value >= 0:
        mode = MODE_LOVE
        reason = "专属羁绊且情绪正向，档位→爱意"
    elif stage in ("亲近", "亲密"):
        mode = MODE_CLOSE
        reason = f"关系阶段「{stage}」，档位→亲近"
    elif _stage_index(stage) >= _stage_index(_STAGE_FAMILIAR) and value >= 0:
        mode = MODE_WARM
        reason = "关系已熟悉且情绪正向，档位→温暖"
    elif value >= 0.2 and float(energy or 0.0) >= 0.6:
        mode = MODE_LIVELY
        reason = "情绪高涨且精力充沛，档位→活泼"
    else:
        mode = MODE_RELAXED
        reason = "默认平和档位"

    hints = style_hints(mode)
    if is_group:
        if mode not in GROUP_ALLOWED_MODES:
            mode = MODE_RELAXED
            hints = style_hints(MODE_RELAXED)
            reason = f"{reason}；群聊档位抑制→放松"
        hints["warmth"] = round(min(float(hints["warmth"]), GROUP_WARMTH_CAP), 4)
    return {"mode": mode, "style_hints": hints, "reason": reason}


# -- affinity application ---------------------------------------------------
def apply_emotion_affinity_delta(
    delta: float,
    *,
    daily_positive_used: float = 0.0,
    daily_negative_used: float = 0.0,
    affinity: float = 0.0,
) -> float:
    """Return the affinity delta actually booked for one emotion event.

    Positive gains go through the shared Phase 1 daily cap; negative events are
    bounded by :data:`EMOTION_DAILY_NEGATIVE_CAP` and by the current affinity so
    it never drops below ``0.0``.
    """
    if delta > 0:
        return effective_delta(delta, daily_positive_used)
    if delta >= 0:
        return 0.0
    remaining = max(0.0, EMOTION_DAILY_NEGATIVE_CAP - max(0.0, daily_negative_used))
    magnitude = min(abs(float(delta)), remaining, max(0.0, float(affinity)))
    return -round(magnitude, 6)
