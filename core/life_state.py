"""Simplified LifeState + weekly-template Schedule.

Phase 1 only models ``activity/energy/scene/summary/as_of`` and derives a
day's state from a weekly recurring template. Relationships and motivation
are explicitly out of scope (T2/T3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_MINUTES_PER_DAY = 24 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


@dataclass(frozen=True)
class LifeState:
    """Minimal life state snapshot for one persona at one instant."""

    persona_id: str
    activity: str
    energy: float
    scene: str
    summary: str
    as_of: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def degraded(cls, persona_id: str, as_of: str | None = None) -> LifeState:
        """Fallback state used when schedule/DB data is unavailable."""
        return cls(
            persona_id=persona_id,
            activity="",
            energy=0.0,
            scene="",
            summary="",
            as_of=as_of or _utcnow().isoformat(),
        )


@dataclass(frozen=True)
class ScheduleEvent:
    """One recurring weekly time block."""

    weekday: int  # 0 = Monday .. 6 = Sunday
    start_min: int  # minutes since local midnight
    end_min: int
    activity: str
    scene: str = ""
    energy: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise ValueError(f"weekday out of range: {self.weekday}")
        if not 0 <= self.start_min < _MINUTES_PER_DAY:
            raise ValueError(f"start_min out of range: {self.start_min}")
        if not 0 <= self.end_min <= _MINUTES_PER_DAY:
            raise ValueError(f"end_min out of range: {self.end_min}")
        if self.end_min < self.start_min:
            raise ValueError("end_min must be >= start_min")

    def covers(self, minute: int) -> bool:
        return self.start_min <= minute < self.end_min

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WeeklySchedule:
    """Weekly recurring template for a single persona."""

    persona_id: str
    events: tuple[ScheduleEvent, ...] = field(default_factory=tuple)

    def events_for(self, day: date) -> list[ScheduleEvent]:
        """Return the day's events sorted by start time."""
        weekday = day.weekday()
        return sorted(
            (e for e in self.events if e.weekday == weekday),
            key=lambda e: (e.start_min, e.end_min),
        )

    @classmethod
    def default_template(cls, persona_id: str) -> WeeklySchedule:
        """A conservative default weekly rhythm used when none is configured."""
        events: list[ScheduleEvent] = []
        for weekday in range(5):  # Mon-Fri
            events.append(
                ScheduleEvent(
                    weekday=weekday,
                    start_min=9 * 60,
                    end_min=12 * 60,
                    activity="working",
                    scene="desk",
                    energy=0.7,
                )
            )
            events.append(
                ScheduleEvent(
                    weekday=weekday,
                    start_min=14 * 60,
                    end_min=18 * 60,
                    activity="working",
                    scene="desk",
                    energy=0.5,
                )
            )
        for weekday in (5, 6):  # Sat-Sun
            events.append(
                ScheduleEvent(
                    weekday=weekday,
                    start_min=10 * 60,
                    end_min=13 * 60,
                    activity="relaxing",
                    scene="home",
                    energy=0.8,
                )
            )
        return cls(persona_id=persona_id, events=tuple(events))

    @classmethod
    def from_rows(cls, persona_id: str, rows) -> WeeklySchedule:
        """Build from DB rows exposing weekday/start_min/end_min/activity/scene/energy."""
        events = []
        for row in rows:
            events.append(
                ScheduleEvent(
                    weekday=int(row["weekday"]),
                    start_min=int(row["start_min"]),
                    end_min=int(row["end_min"]),
                    activity=str(row["activity"]),
                    scene=str(row["scene"] or ""),
                    energy=float(row["energy"] or 0.0),
                )
            )
        return cls(persona_id=persona_id, events=tuple(events))


def generate_life_state(
    schedule: WeeklySchedule,
    persona_id: str,
    moment: datetime | None = None,
) -> LifeState:
    """Derive a :class:`LifeState` from the schedule at ``moment``.

    Falls back to a degraded idle state when no event covers the instant.
    """
    moment = moment or _utcnow()
    minute = _minutes_of_day(moment)
    as_of = moment.isoformat()

    matching = [e for e in schedule.events_for(moment.date()) if e.covers(minute)]
    if not matching:
        return LifeState(
            persona_id=persona_id,
            activity="idle",
            energy=0.4,
            scene="",
            summary="暂无安排，处于空闲状态。",
            as_of=as_of,
        )

    event = matching[0]
    summary = f"当前正在{event.activity}"
    if event.scene:
        summary += f"（{event.scene}）"
    summary += "。"
    return LifeState(
        persona_id=persona_id,
        activity=event.activity,
        energy=event.energy,
        scene=event.scene,
        summary=summary,
        as_of=as_of,
    )


def _format_minutes(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def materialize_day(schedule: WeeklySchedule, day: date) -> list[dict]:
    """Expand the weekly template into the concrete events for ``day``."""
    return [
        {
            "date": day.isoformat(),
            "start": _format_minutes(event.start_min),
            "end": _format_minutes(event.end_min),
            "activity": event.activity,
            "scene": event.scene,
            "energy": event.energy,
        }
        for event in schedule.events_for(day)
    ]
