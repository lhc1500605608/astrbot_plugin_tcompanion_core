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

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from .emotion import DAMPING_STATES
from .relationship import (
    STAGE_ORDER,
    STAGE_STRANGER,
    ignored_decay_factor,
)

#: Longest stored/dispatched open-thread label (short tag, never raw text).
THREAD_TITLE_MAX = 40
#: Default number of open threads surfaced in ``get_proactive_context``.
DEFAULT_OPEN_THREAD_LIMIT = 3

#: Open-thread kinds (fail-closed: anything else is rejected upstream).
OPEN_THREAD_KIND_COMMITMENT = "commitment"
OPEN_THREAD_KIND_PENDING_QUESTION = "pending_question"
OPEN_THREAD_KIND_PLAN = "plan"
OPEN_THREAD_KIND_TOPIC = "topic"
OPEN_THREAD_KINDS: tuple[str, ...] = (
    OPEN_THREAD_KIND_COMMITMENT,
    OPEN_THREAD_KIND_PENDING_QUESTION,
    OPEN_THREAD_KIND_PLAN,
    OPEN_THREAD_KIND_TOPIC,
)

#: Open-thread statuses.
OPEN_THREAD_STATUS_OPEN = "open"
OPEN_THREAD_STATUS_STALE = "stale"
OPEN_THREAD_STATUS_CLOSED = "closed"

#: Lifecycle thresholds (defaults; user-overridable via the ``open_thread``
#: config group — see ``docs/CONTRACT.md`` §13).
OPEN_THREAD_TTL_DAYS = 3
OPEN_THREAD_EXPIRE_DAYS = 14
OPEN_THREAD_MAX = 20
OPEN_THREAD_FOLLOWUP_MAX = 2


@dataclass(frozen=True)
class OpenThreadConfig:
    """Effective ``open_thread`` config group (already coerced + defaulted).

    ``enabled=False`` turns the whole open-thread section off; ``max_open`` is
    the per-scope retention cap, ``ttl_days``/``expire_days`` drive the
    lifecycle, ``followup_max`` is exposed for the downstream follow-up cap.
    """

    enabled: bool = True
    max_open: int = OPEN_THREAD_MAX
    ttl_days: int = OPEN_THREAD_TTL_DAYS
    expire_days: int = OPEN_THREAD_EXPIRE_DAYS
    followup_max: int = OPEN_THREAD_FOLLOWUP_MAX

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


def parse_open_thread_config(config) -> OpenThreadConfig:
    """Read the ``open_thread`` group from an AstrBot config mapping.

    Fail-safe: a missing/!mapping group or an unparseable value falls back to
    the documented default, so a malformed config never disables the section
    or raises into a read path. Parsed fresh on each call (config hot-reload
    mutates the injected ``AstrBotConfig`` in place).
    """
    section: dict = {}
    if isinstance(config, dict):
        raw = config.get("open_thread")
        if isinstance(raw, dict):
            section = raw
    return OpenThreadConfig(
        enabled=_cfg_bool(section.get("enabled"), True),
        max_open=_cfg_int(section.get("max"), OPEN_THREAD_MAX),
        ttl_days=_cfg_int(section.get("ttl_days"), OPEN_THREAD_TTL_DAYS),
        expire_days=_cfg_int(section.get("expire_days"), OPEN_THREAD_EXPIRE_DAYS),
        followup_max=_cfg_int(section.get("followup_max"), OPEN_THREAD_FOLLOWUP_MAX),
    )

#: Candidate score floor by source (frozen tuning; see docs/CONTRACT.md §10).
OPEN_THREAD_BASE = 0.70
OPEN_THREAD_RECENCY_BONUS = 0.15
#: Label-free wording for an open-thread motivation. The short label must never
#: ride the reason: it is injected only through the gated follow-up block, so a
#: label here would bypass the downstream cooldown/cap/switch (TMEAAA-504).
OPEN_THREAD_REASON = "有件对方提过、还没收尾的事，想找机会提一句。"
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


#: Ranking-only bonus when a candidate label overlaps a memory hint (v1.3).
MEMORY_HINT_BONUS = 0.05


def _memory_hint_bonus(label: str, hint_norms: tuple[str, ...], *, ngram: int = 2) -> float:
    """Return :data:`MEMORY_HINT_BONUS` when ``label`` overlaps any hint.

    Zero-LLM substring overlap: the candidate label matches if it contains a
    hint outright or shares any ``ngram``-character substring of a hint (a
    CJK-friendly signal, e.g. both mention 「论文」). Ranking only: the caller's
    gates (``allow`` / ``adopted`` / ``blocked_reason`` / lifecycle) are never
    affected by this value.
    """
    if not hint_norms:
        return 0.0
    norm_label = " ".join(str(label or "").split()).lower()
    if not norm_label:
        return 0.0
    for hint in hint_norms:
        if len(hint) < ngram:
            continue
        if hint in norm_label:
            return MEMORY_HINT_BONUS
        if any(hint[index : index + ngram] in norm_label for index in range(len(hint) - ngram + 1)):
            return MEMORY_HINT_BONUS
    return 0.0


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


def thread_id_for(kind: str, label: str, *, dedupe_key: str | None = None) -> str:
    """Derive a stable thread id so repeated mentions bump instead of insert.

    Callers may pin the id with ``dedupe_key``; otherwise it is a short hash of
    ``kind|normalized label`` — the same unfinished item always maps to the same
    row. The id never contains the raw label.
    """
    if dedupe_key:
        return str(dedupe_key)
    normalized = sanitize_thread_title(label).lower()
    digest = hashlib.sha1(f"{kind}|{normalized}".encode()).hexdigest()[:12]
    return f"thread:{digest}"


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
    thread_id: str | None = None

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
    open_thread_details: Sequence[dict] = (),
    allow: bool = True,
    emotion_state: str = "",
    memory_hints: Sequence[str] = (),
    quiet: bool = False,
) -> MotivationResult:
    """Fuse life event + open threads + time window into a scored candidate set.

    Deterministic: candidates are sorted by ``(-score, key)`` and scores are
    clamped/rounded, so identical inputs always produce an identical result.
    ``adopted`` is false when the unanswered streak is too high or the quota
    does not allow outreach; the reason is still reported so the outcome stays
    auditable.

    ``open_thread_details`` (additive) carries ``{label, thread_id}`` so the
    candidate set can echo the owning ``thread_id`` back to the caller; when it
    is empty the plain ``open_threads`` labels are used and ``thread_id`` is
    ``None``.

    Open-thread candidates carry a **label-free** ``reason`` (label only in the
    audit ``label`` field): the short label is injected downstream solely through
    the gated follow-up block, so putting it in ``reason`` would leak past the
    cooldown/cap/switch gate (TMEAAA-504).

    ``emotion_state`` may only *dampen* the scores (``回避``/``受伤``, see
    ``emotion.DAMPING_STATES``) — a positive emotion never boosts outreach.

    ``memory_hints`` (additive v1.3) are profile-derived strings used purely as
    a **ranking** signal: a candidate whose label overlaps any hint gains at
    most :data:`MEMORY_HINT_BONUS`. Gates, lifecycle and ``adopted`` are
    unaffected (see ``docs/CONTRACT.md`` §14).

    ``quiet`` (additive v1.4) is the effective quiet-hours flag for a private
    scope. Gate priority is ``unanswered_streak`` > ``quiet`` > ``quota``: when
    set, ``blocked_reason`` becomes ``"quiet_hours"`` and ``adopted`` is false,
    independently of ``allow`` (the caller also flips ``quota.allow`` false).
    """
    index = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    stage_bonus = STAGE_BONUS_STEP * index
    decay = ignored_decay_factor(unanswered_streak) * DAMPING_STATES.get(emotion_state, 1.0)
    hint_norms = tuple(
        norm
        for norm in (" ".join(str(hint or "").split()).lower() for hint in memory_hints or ())
        if len(norm) >= 2
    )
    candidates: list[MotivationCandidate] = []

    pairs: list[tuple[str, str | None]] = []
    if open_thread_details:
        for detail in open_thread_details:
            label = str(detail.get("label") or detail.get("title") or "")
            if label:
                pairs.append((label, detail.get("thread_id")))
    else:
        pairs = [(label, None) for label in open_threads]

    for position, (label, thread_id) in enumerate(pairs):
        recency = OPEN_THREAD_RECENCY_BONUS if position == 0 else 0.0
        candidates.append(
            MotivationCandidate(
                key=f"open_thread:{position}",
                label=label,
                reason=OPEN_THREAD_REASON,
                score=clamp01(
                    (OPEN_THREAD_BASE + recency + stage_bonus) * decay
                    + _memory_hint_bonus(label, hint_norms)
                ),
                thread_id=thread_id,
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
                score=clamp01(
                    (LIFE_EVENT_BASE + energy_bonus + stage_bonus) * decay
                    + _memory_hint_bonus(activity, hint_norms)
                ),
            )
        )

    window_key, window_label = time_window(moment.hour)
    candidates.append(
        MotivationCandidate(
            key=f"time:{window_key}",
            label=window_label,
            reason=f"现在是{window_label}，{_TIME_WINDOW_HINTS[window_key]}",
            score=clamp01(
                (TIME_WINDOW_BASE + stage_bonus) * decay
                + _memory_hint_bonus(window_label, hint_norms)
            ),
        )
    )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.key))
    selected = candidates[0] if candidates else None

    if unanswered_streak >= MAX_UNANSWERED_FOR_CONTEXT:
        blocked_reason = "unanswered_streak"
    elif quiet:
        blocked_reason = "quiet_hours"
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
