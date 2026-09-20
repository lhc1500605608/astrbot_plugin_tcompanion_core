"""Motivation fusion, open-thread labels, and downstream expression hints.

Pure domain logic (no SQLite): given the derived inputs already owned by the
core (life state, open-thread short labels, relationship stage, unanswered
streak, time of day) this module produces a **deterministic** ranked candidate
set plus the selected reason. The same inputs always yield the same output, so
audit rows are reproducible (see ``docs/CONTRACT.md`` §10).

Privacy invariant: open threads are reduced to **short labels** only — never
message bodies. :func:`sanitize_thread_title` collapses whitespace and caps the
length so a caller can never smuggle raw text through this path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from .relationship import (
    STAGE_ORDER,
    STAGE_STRANGER,
    ignored_decay_factor,
)

#: Longest stored/dispatched open-thread label (short tag, never raw text).
THREAD_TITLE_MAX = 40
#: Default number of open threads surfaced in ``get_proactive_context``.
DEFAULT_OPEN_THREAD_LIMIT = 3

#: Candidate score floor by source (frozen tuning; see docs/CONTRACT.md §10).
OPEN_THREAD_BASE = 0.70
OPEN_THREAD_RECENCY_BONUS = 0.15
LIFE_EVENT_BASE = 0.45
TIME_WINDOW_BASE = 0.30
#: Per-stage additive bonus (index into ``STAGE_ORDER``) capped at 4 steps.
STAGE_BONUS_STEP = 0.05
#: A streak at/above this blocks adoption (still reported for traceability).
MAX_UNANSWERED_FOR_CONTEXT = 3

#: Proactive quota (Phase 1: companion-core never sends itself, only advises).
QUOTA_DAILY_LIMIT = 3
QUOTA_HOURLY_LIMIT = 1

_TIME_WINDOW_HINTS: dict[str, str] = {
    "morning": "适合道声早安。",
    "midday": "可以问问她吃了没。",
    "afternoon": "适合随口聊聊近况。",
    "evening": "可以分享点轻松的小事。",
    "night": "夜深了，适合轻声一句。",
}

#: Address / warmth / proactive bias per relationship stage.
_EXPRESSION_BY_STAGE: dict[str, tuple[str, float, float]] = {
    STAGE_STRANGER: ("您", 0.20, -0.20),
    "眼熟": ("您", 0.35, -0.10),
    "熟悉": ("你", 0.50, 0.0),
    "亲近": ("你", 0.70, 0.10),
    "亲密": ("你", 0.90, 0.20),
}

_MODE_BY_STAGE: dict[str, str] = {
    STAGE_STRANGER: "疏离",
    "眼熟": "礼貌",
    "熟悉": "放松",
    "亲近": "亲近",
    "亲密": "亲密",
}


def clamp01(value: float) -> float:
    """Clamp a score into ``[0.0, 1.0]`` rounded to 4 dp."""
    return round(min(1.0, max(0.0, float(value))), 4)


def sanitize_thread_title(title: str, *, max_len: int = THREAD_TITLE_MAX) -> str:
    """Reduce arbitrary text to a short, single-line open-thread label.

    Collapses all whitespace, drops control chars, and truncates with an
    ellipsis. This is the only path by which a title can be persisted, so the
    privacy invariant (short tag, never raw text) is enforced here.
    """
    cleaned = " ".join(str(title or "").split())
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def time_window(hour: int) -> tuple[str, str]:
    """Map an hour (0-23) to a stable ``(key, chinese_label)`` window."""
    if 5 <= hour < 11:
        return "morning", "早上"
    if 11 <= hour < 14:
        return "midday", "中午"
    if 14 <= hour < 18:
        return "afternoon", "下午"
    if 18 <= hour < 23:
        return "evening", "晚上"
    return "night", "深夜"


def relationship_mode(stage: str, bond: bool = False) -> str:
    """Return the downstream interaction mode implied by stage/bond."""
    if bond:
        return "默契"
    return _MODE_BY_STAGE.get(stage, _MODE_BY_STAGE[STAGE_STRANGER])


def expression_hints(stage: str, bond: bool = False, unanswered_streak: int = 0) -> dict:
    """Derive ``{address, warmth, proactive_bias}`` from stage/bond/streak.

    These are *inputs* for the downstream expression layer (kanjyou); this
    module never authors user-facing phrasing. A positive proactive bias is
    damped by the unanswered streak so ignored outreach gets quieter.
    """
    address, warmth, bias = _EXPRESSION_BY_STAGE.get(stage, _EXPRESSION_BY_STAGE[STAGE_STRANGER])
    if bond:
        warmth = min(1.0, warmth + 0.1)
    if bias > 0:
        bias = bias * ignored_decay_factor(unanswered_streak)
    return {
        "address": address,
        "warmth": round(warmth, 4),
        "proactive_bias": round(bias, 4),
    }


def build_quota(daily_used: int, hourly_used: int) -> dict:
    """Return the frozen quota structure from already-consumed counts."""
    daily_remaining = max(0, QUOTA_DAILY_LIMIT - max(0, int(daily_used)))
    hourly_remaining = max(0, QUOTA_HOURLY_LIMIT - max(0, int(hourly_used)))
    return {
        "hourly_remaining": hourly_remaining,
        "daily_remaining": daily_remaining,
        "allow": daily_remaining > 0 and hourly_remaining > 0,
    }


@dataclass(frozen=True)
class MotivationCandidate:
    """One scored reason to reach out, with its traceable rationale."""

    key: str
    label: str
    reason: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MotivationResult:
    """Deterministic fusion result for one proactive decision point."""

    candidates: tuple[MotivationCandidate, ...] = ()
    selected: MotivationCandidate | None = None
    score: float = 0.0
    reason: str = ""
    adopted: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "score": self.score,
            "adopted": self.adopted,
            "blocked_reason": self.blocked_reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def fuse_motivation(
    *,
    moment: datetime,
    stage: str = STAGE_STRANGER,
    bond: bool = False,
    unanswered_streak: int = 0,
    activity: str = "",
    energy: float = 0.0,
    scene: str = "",
    open_threads: Sequence[str] = (),
    allow: bool = True,
) -> MotivationResult:
    """Fuse life event + open threads + time window into a scored candidate set.

    Deterministic: candidates are sorted by ``(-score, key)`` and scores are
    clamped/rounded, so identical inputs always produce an identical result.
    ``adopted`` is false when the unanswered streak is too high or the quota
    does not allow outreach; the reason is still reported so the outcome stays
    auditable.
    """
    index = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    stage_bonus = STAGE_BONUS_STEP * index
    decay = ignored_decay_factor(unanswered_streak)
    candidates: list[MotivationCandidate] = []

    for position, label in enumerate(open_threads):
        recency = OPEN_THREAD_RECENCY_BONUS if position == 0 else 0.0
        candidates.append(
            MotivationCandidate(
                key=f"open_thread:{position}",
                label=label,
                reason=f"未完成话题「{label}」，想找机会收个尾。",
                score=clamp01((OPEN_THREAD_BASE + recency + stage_bonus) * decay),
            )
        )

    if activity:
        energy_bonus = min(0.10, max(0.0, float(energy)) * 0.10)
        reason = f"她此刻正在{activity}"
        if scene:
            reason += f"（{scene}）"
        reason += "，顺手想跟你说说。"
        candidates.append(
            MotivationCandidate(
                key="life_event",
                label=activity,
                reason=reason,
                score=clamp01((LIFE_EVENT_BASE + energy_bonus + stage_bonus) * decay),
            )
        )

    window_key, window_label = time_window(moment.hour)
    candidates.append(
        MotivationCandidate(
            key=f"time:{window_key}",
            label=window_label,
            reason=f"现在是{window_label}，{_TIME_WINDOW_HINTS[window_key]}",
            score=clamp01((TIME_WINDOW_BASE + stage_bonus) * decay),
        )
    )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.key))
    selected = candidates[0] if candidates else None

    if unanswered_streak >= MAX_UNANSWERED_FOR_CONTEXT:
        blocked_reason = "unanswered_streak"
    elif not allow:
        blocked_reason = "quota"
    else:
        blocked_reason = ""

    adopted = selected is not None and not blocked_reason
    return MotivationResult(
        candidates=tuple(candidates),
        selected=selected,
        score=selected.score if selected else 0.0,
        reason=selected.reason if selected else "",
        adopted=adopted,
        blocked_reason=blocked_reason,
    )
