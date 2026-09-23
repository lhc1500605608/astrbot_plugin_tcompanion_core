"""Lightweight growth: deterministic derivation from the existing ledger.

Pure domain logic (no SQLite, zero LLM): growth is *derived*, never ingested.
The relationship ledger (affinity / stage), the emotion events and the number of
active days are the only inputs, so the same state always yields the same level
(see ``docs/CONTRACT.md`` §18).

Invariants:

* **Bounded**: the level never exceeds ``max_level`` and the expression drift
  never exceeds ``drift_cap`` (hard-capped at :data:`GROWTH_DRIFT_HARD_CAP`).
* **Never changes the mode**: growth only nudges ``style_hints["warmth"]``.
* **Rollback**: a disabled or reset section yields no growth and no drift, so
  expression and storage fall back to the previous behaviour.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .emotion import style_hints
from .relationship import STAGE_CLOSE, STAGE_FAMILIAR, STAGE_INTIMATE

# -- defaults / caps -------------------------------------------------------
GROWTH_MAX_LEVEL_DEFAULT = 10
GROWTH_DRIFT_CAP_DEFAULT = 0.05
#: Hard ceiling for ``drift_cap`` — a caller can never inflate warmth further.
GROWTH_DRIFT_HARD_CAP = 0.05
#: Verbosity drift is a fixed fraction of the warmth drift.
GROWTH_VERBOSITY_RATIO = 0.5
#: Days of activity that contribute at most one extra level (consistency).
GROWTH_ACTIVE_DAYS_SPAN = 30.0

#: Trait labels (short, non-intimate wording for group-safe display).
TRAIT_FAMILIAR = "熟悉"
TRAIT_CLOSE = "亲近"
TRAIT_FREQUENT = "常来"
TRAIT_REGULAR = "熟客"
TRAIT_CHEERFUL = "开朗"


@dataclass(frozen=True)
class GrowthConfig:
    """Effective ``growth`` config group (coerced + defaulted)."""

    enabled: bool = True
    max_level: int = GROWTH_MAX_LEVEL_DEFAULT
    drift_cap: float = GROWTH_DRIFT_CAP_DEFAULT
    reset: bool = False

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


def _cfg_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_growth_config(config) -> GrowthConfig:
    """Read the ``growth`` group; defaults on any missing/malformed value."""
    section: dict = {}
    if isinstance(config, dict):
        raw = config.get("growth")
        if isinstance(raw, dict):
            section = raw
    return GrowthConfig(
        enabled=_cfg_bool(section.get("enabled"), True),
        max_level=max(0, _cfg_int(section.get("max_level"), GROWTH_MAX_LEVEL_DEFAULT)),
        drift_cap=max(0.0, min(GROWTH_DRIFT_HARD_CAP, _cfg_float(
            section.get("drift_cap"), GROWTH_DRIFT_CAP_DEFAULT
        ))),
        reset=_cfg_bool(section.get("reset"), False),
    )


def growth_available(cfg: GrowthConfig) -> bool:
    """Growth is observable only while enabled and not reset."""
    return bool(cfg.enabled) and not bool(cfg.reset)


def _clamp01(value) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def derive_xp(affinity: float, active_days: int, max_level: int) -> float:
    """Deterministic experience: affinity (0..1) scaled to levels + consistency."""
    span = max(1, int(max_level))
    base = _clamp01(affinity) * span
    consistency = min(1.0, max(0, int(active_days or 0)) / GROWTH_ACTIVE_DAYS_SPAN)
    return round(base + consistency, 4)


def derive_level(affinity: float, active_days: int, max_level: int) -> tuple[int, float]:
    """Return ``(level, progress)`` — level bounded by ``max_level``."""
    cap = max(0, int(max_level))
    xp = derive_xp(affinity, active_days, cap)
    level = min(cap, int(xp))
    if cap and level >= cap:
        progress = 1.0
    else:
        progress = round(min(1.0, max(0.0, xp - level)), 4)
    return level, progress


def derive_traits(
    stage: str, active_days: int, positive_ratio: float, *, event_count: int = 0
) -> list[str]:
    """Derive a short, bounded trait list from stage/activity/positivity."""
    traits: list[str] = []
    if stage in (STAGE_CLOSE, STAGE_INTIMATE):
        traits.append(TRAIT_CLOSE)
    elif stage == STAGE_FAMILIAR:
        traits.append(TRAIT_FAMILIAR)
    if int(active_days or 0) >= 14:
        traits.append(TRAIT_FREQUENT)
    elif int(active_days or 0) >= 5:
        traits.append(TRAIT_REGULAR)
    if int(event_count or 0) >= 3 and _clamp01(positive_ratio) >= 0.6:
        traits.append(TRAIT_CHEERFUL)
    return traits


def derive_drift(level: int, max_level: int, drift_cap: float) -> dict:
    """Return the bounded ``{warmth_delta, verbosity_delta}`` growth drift."""
    cap = max(0.0, min(GROWTH_DRIFT_HARD_CAP, float(drift_cap or 0.0)))
    span = max(1, int(max_level))
    ratio = min(1.0, max(0, int(level or 0)) / span)
    warmth_delta = round(cap * ratio, 4)
    return {
        "warmth_delta": warmth_delta,
        "verbosity_delta": round(warmth_delta * GROWTH_VERBOSITY_RATIO, 4),
    }


def build_growth(
    *,
    affinity: float,
    active_days: int,
    stage: str,
    positive_ratio: float,
    event_count: int,
    max_level: int,
    drift_cap: float,
) -> dict:
    """Assemble the derived growth block (``level`` / ``progress`` / ``traits``)."""
    level, progress = derive_level(affinity, active_days, max_level)
    return {
        "level": level,
        "progress": progress,
        "max_level": max(0, int(max_level)),
        "traits": derive_traits(
            stage, active_days, positive_ratio, event_count=event_count
        ),
    }


def with_growth_drift(decision: dict, warmth_delta: float) -> dict:
    """Raise ``style_hints.warmth`` by a bounded drift; never change ``mode``.

    The added amount is capped by ``warmth_delta`` (already bounded by
    ``drift_cap``) and by the remaining room up to ``1.0``. Without a positive
    drift the ``decision`` is returned untouched.
    """
    try:
        add = float(warmth_delta)
    except (TypeError, ValueError):
        return decision
    if add <= 0:
        return decision
    hints = dict(decision.get("style_hints") or {})
    mode = decision.get("mode")
    base = float(style_hints(mode).get("warmth", 0.0)) if mode else 0.0
    try:
        current = float(hints.get("warmth") or base)
    except (TypeError, ValueError):
        current = base
    hints["warmth"] = round(min(1.0, current + add), 4)
    return {**decision, "style_hints": hints}
