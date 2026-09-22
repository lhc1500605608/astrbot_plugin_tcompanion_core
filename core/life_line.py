"""Life line (v1.4 · Phase 2-D): config, time windows, sleep inference, diary.

Pure, deterministic, zero-LLM logic (no SQLite, no network). The contract layer
combines these helpers with the store and the optional weather client.

Privacy: only structured values pass through here — time windows, event codes
and a synthesized summary. Raw message text never enters this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

MINUTES_PER_DAY = 24 * 60

#: Frozen defaults.
DEFAULT_QUIET_HOURS = "23:00-07:30"
DEFAULT_SLEEP_START = 23 * 60
DEFAULT_SLEEP_END = 7 * 60 + 30
DEFAULT_MEAL_WINDOWS: dict[str, str] = {
    "breakfast": "07:00-09:00",
    "lunch": "11:30-13:00",
    "dinner": "18:00-20:00",
}
MEAL_LABELS: dict[str, str] = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}

#: Sleep-inference bounds (D2).
SLEEP_INFER_DAYS = 14
SLEEP_MIN_BLOCK_MIN = 4 * 60
SLEEP_ACTIVE_DAY_MIN = 3
SLEEP_MESSAGE_MIN = 10
SLEEP_ONSET_FLOOR = 20 * 60  # 20:00
SLEEP_ONSET_CEIL = 3 * 60  # 03:00
SLEEP_WAKE_FLOOR = 5 * 60  # 05:00
SLEEP_WAKE_CEIL = 11 * 60  # 11:00

#: A recent user interaction (minutes) exempts quiet-hours suppression.
QUIET_INTERACTION_GRACE_MIN = 10


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
        return int(value)
    except (TypeError, ValueError):
        return default


def _cfg_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LifeLineConfig:
    """Effective ``life_line`` config group (already coerced + defaulted)."""

    enabled: bool = True
    city: str = ""
    weather_api_base: str = ""
    weather_timeout_sec: float = 3.0
    weather_ttl_min: int = 45
    meal_reminders_enabled: bool = True
    breakfast_window: str = DEFAULT_MEAL_WINDOWS["breakfast"]
    lunch_window: str = DEFAULT_MEAL_WINDOWS["lunch"]
    dinner_window: str = DEFAULT_MEAL_WINDOWS["dinner"]
    sleep_window_auto: bool = True
    quiet_hours: str = DEFAULT_QUIET_HOURS
    proactive_opt_in: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def meal_windows(self) -> dict[str, tuple[int, int]]:
        """Return the valid meal windows as ``{slot: (start_min, end_min)}``."""
        raw = {
            "breakfast": self.breakfast_window,
            "lunch": self.lunch_window,
            "dinner": self.dinner_window,
        }
        parsed: dict[str, tuple[int, int]] = {}
        for slot, text in raw.items():
            window = parse_window(text)
            if window is not None:
                parsed[slot] = window
        return parsed

    def quiet_window(self) -> tuple[int, int] | None:
        return parse_window(self.quiet_hours)


def parse_life_line_config(config) -> LifeLineConfig:
    """Read the ``life_line`` group from an AstrBot config mapping.

    Accepts the nested group (``{"life_line": {...}}``) and flat
    ``life_line_*`` / ``life_city`` keys. Fail-safe: a missing group or an
    unparseable value falls back to the documented default. Re-parsed on each
    call because AstrBot hot-reload mutates the injected mapping in place.
    """
    mapping = config if isinstance(config, dict) else {}
    section = mapping.get("life_line")
    if not isinstance(section, dict):
        section = {}

    def pick(name: str, default, *, flat: str | None = None, aliases: tuple[str, ...] = ()):
        if name in section:
            return section[name]
        for alias in aliases:
            if alias in section:
                return section[alias]
        if flat and flat in mapping:
            return mapping[flat]
        return default

    return LifeLineConfig(
        enabled=_cfg_bool(
            pick("enabled", True, flat="life_line_enabled", aliases=("life_line_enabled",)),
            True,
        ),
        city=str(pick("life_city", "", flat="life_city") or "").strip(),
        weather_api_base=str(
            pick("weather_api_base", "", flat="weather_api_base") or ""
        ).strip(),
        weather_timeout_sec=_cfg_float(
            pick("weather_timeout_sec", 3.0, flat="weather_timeout_sec"), 3.0
        ),
        weather_ttl_min=_cfg_int(
            pick("weather_ttl_min", 45, flat="weather_ttl_min"), 45
        ),
        meal_reminders_enabled=_cfg_bool(
            pick("meal_reminders_enabled", True, flat="meal_reminders_enabled"), True
        ),
        breakfast_window=str(
            pick("breakfast_window", DEFAULT_MEAL_WINDOWS["breakfast"])
            or DEFAULT_MEAL_WINDOWS["breakfast"]
        ),
        lunch_window=str(
            pick("lunch_window", DEFAULT_MEAL_WINDOWS["lunch"])
            or DEFAULT_MEAL_WINDOWS["lunch"]
        ),
        dinner_window=str(
            pick("dinner_window", DEFAULT_MEAL_WINDOWS["dinner"])
            or DEFAULT_MEAL_WINDOWS["dinner"]
        ),
        sleep_window_auto=_cfg_bool(
            pick("sleep_window_auto", True, flat="sleep_window_auto"), True
        ),
        quiet_hours=str(
            pick("quiet_hours", DEFAULT_QUIET_HOURS, flat="quiet_hours")
            or DEFAULT_QUIET_HOURS
        ),
        proactive_opt_in=_cfg_bool(
            pick("proactive_opt_in", False, flat="proactive_opt_in"), False
        ),
    )


# -- time windows -----------------------------------------------------------
def parse_hhmm(text: str) -> int | None:
    """Parse ``"HH:MM"`` into minutes since midnight (``None`` when invalid)."""
    try:
        hour_text, minute_text = str(text).strip().split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


def parse_window(text: str) -> tuple[int, int] | None:
    """Parse ``"HH:MM-HH:MM"``; supports windows crossing midnight."""
    parts = str(text or "").split("-")
    if len(parts) != 2:
        return None
    start, end = parse_hhmm(parts[0]), parse_hhmm(parts[1])
    if start is None or end is None or start == end:
        return None
    return start, end


def in_window(minute: int, window: tuple[int, int]) -> bool:
    """Return whether ``minute`` falls inside ``window`` (wrap-aware)."""
    start, end = window
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end


def format_minutes(minute: int) -> str:
    minute = int(minute) % MINUTES_PER_DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


# -- meals ------------------------------------------------------------------
def meal_slot_at(minute: int, windows: dict[str, tuple[int, int]]) -> str | None:
    for slot in ("breakfast", "lunch", "dinner"):
        window = windows.get(slot)
        if window is not None and in_window(minute, window):
            return slot
    return None


def meal_view(minute: int, windows: dict[str, tuple[int, int]]) -> dict | None:
    """Return ``{slot,label,at,in_window,windows}`` for the nearest meal."""
    if not windows:
        return None
    current = meal_slot_at(minute, windows)
    if current is not None:
        start, _ = windows[current]
        return {
            "slot": current,
            "label": MEAL_LABELS.get(current, current),
            "at": format_minutes(start),
            "in_window": True,
            "windows": {slot: f"{format_minutes(s)}-{format_minutes(e)}" for slot, (s, e) in windows.items()},
        }
    upcoming = sorted(
        ((slot, window[0]) for slot, window in windows.items() if window[0] > minute),
        key=lambda item: item[1],
    )
    if not upcoming:
        upcoming = sorted(
            ((slot, window[0]) for slot, window in windows.items()), key=lambda item: item[1]
        )
    slot, start = upcoming[0] if upcoming else (None, None)
    if slot is None:
        return None
    return {
        "slot": slot,
        "label": MEAL_LABELS.get(slot, slot),
        "at": format_minutes(start),
        "in_window": False,
        "windows": {s: f"{format_minutes(ws)}-{format_minutes(we)}" for s, (ws, we) in windows.items()},
    }


# -- sleep inference --------------------------------------------------------
def _parse_iso(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clamp_onset(minute: int) -> int:
    minute %= MINUTES_PER_DAY
    if SLEEP_ONSET_CEIL < minute < SLEEP_ONSET_FLOOR:
        # In the disallowed daytime band: snap to the nearer bound.
        return SLEEP_ONSET_FLOOR if (SLEEP_ONSET_FLOOR - minute) <= (minute - SLEEP_ONSET_CEIL) else SLEEP_ONSET_CEIL
    return minute


def _clamp_wake(minute: int) -> int:
    return max(SLEEP_WAKE_FLOOR, min(SLEEP_WAKE_CEIL, minute % MINUTES_PER_DAY))


def infer_sleep_window(
    stamps: Sequence[str], *, now: datetime | None = None
) -> tuple[int, int, str]:
    """Infer a ``(onset, wake, source)`` sleep window from recent activity.

    Zero-collection: uses the hour-of-day histogram of recent private-scope
    interaction timestamps. The longest contiguous zero-activity block (at least
    :data:`SLEEP_MIN_BLOCK_MIN`, wrapping midnight) yields the onset (the last
    active hour before it) and the wake hour (the first active hour after it).
    Insufficient samples fall back to ``23:00-07:30`` with ``source="default"``.
    """
    hours: list[int] = []
    days: set[str] = set()
    for stamp in stamps or ():
        moment = _parse_iso(stamp)
        if moment is None:
            continue
        hours.append(moment.hour)
        days.add(moment.date().isoformat())
    if len(days) < SLEEP_ACTIVE_DAY_MIN or len(hours) < SLEEP_MESSAGE_MIN:
        return DEFAULT_SLEEP_START, DEFAULT_SLEEP_END, "default"

    active = sorted(set(hours))
    if len(active) == 1:
        only = active[0]
        onset = _clamp_onset((only + 1) * 60)
        wake = _clamp_wake(only * 60)
        return onset, wake, "inferred"

    best_len = -1
    best_before = active[0]
    best_after = active[0]
    count = len(active)
    for index, before in enumerate(active):
        after = active[(index + 1) % count]
        gap = (after - before - 1) % MINUTES_PER_DAY
        if gap > best_len:
            best_len = gap
            best_before = before
            best_after = after
    if best_len < SLEEP_MIN_BLOCK_MIN // 60:
        return DEFAULT_SLEEP_START, DEFAULT_SLEEP_END, "default"

    onset = _clamp_onset((best_before + 1) * 60)
    wake = _clamp_wake(best_after * 60)
    return onset, wake, "inferred"


def effective_quiet_window(
    cfg: LifeLineConfig, sleep_window: tuple[int, int] | None
) -> tuple[int, int] | None:
    """Pick the suppression window: inferred sleep (auto) else ``quiet_hours``."""
    if cfg.sleep_window_auto and sleep_window is not None:
        return sleep_window
    return cfg.quiet_window()


# -- diary ------------------------------------------------------------------
def synthesize_diary(
    day: str,
    *,
    sleep_window: tuple[int, int] | None = None,
    meals: Sequence[str] = (),
    activity: str = "",
    mood: str = "",
) -> dict:
    """Deterministically compose a day's diary from structured inputs.

    Zero LLM, zero raw text: a fixed template over the sleep window, the meal
    slots seen that day, the day's activity and the emotion mood.
    """
    parts: list[str] = []
    if sleep_window is not None:
        parts.append(f"{format_minutes(sleep_window[0])}–{format_minutes(sleep_window[1])} 在休息")
    meal_labels = [MEAL_LABELS.get(slot, str(slot)) for slot in meals]
    if meal_labels:
        parts.append(f"吃了{'、'.join(meal_labels)}")
    if activity:
        parts.append(f"主要在{activity}")
    body = "；".join(part for part in parts if part)
    mood_text = mood or "平静"
    if body:
        summary = f"{day}：{body}。心情{mood_text}。"
    else:
        summary = f"{day}：平静的一天。心情{mood_text}。"
    return {"day": day, "summary": summary, "mood": mood_text}


@dataclass(frozen=True)
class LifeLineSnapshot:
    """Public life-line snapshot (structured values only)."""

    day: str
    weather: dict | None = None
    meal: dict | None = None
    sleep: dict | None = None
    quiet: bool = False
    diary: dict | None = None
    windows: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
