from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core.life_state import (
    LifeState,
    ScheduleEvent,
    WeeklySchedule,
    generate_life_state,
    materialize_day,
)


def test_schedule_event_validates_range():
    with pytest.raises(ValueError):
        ScheduleEvent(weekday=7, start_min=0, end_min=10, activity="x")
    with pytest.raises(ValueError):
        ScheduleEvent(weekday=0, start_min=100, end_min=50, activity="x")


def test_default_template_events_for_weekday():
    schedule = WeeklySchedule.default_template("p1")
    monday = date(2026, 9, 21)  # Monday
    events = schedule.events_for(monday)
    assert [e.start_min for e in events] == [9 * 60, 14 * 60]

    sunday = date(2026, 9, 27)
    assert [e.activity for e in schedule.events_for(sunday)] == ["relaxing"]


def test_generate_life_state_inside_event():
    schedule = WeeklySchedule.default_template("p1")
    moment = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)  # Mon 09:30
    state = generate_life_state(schedule, "p1", moment)
    assert state.activity == "working"
    assert state.scene == "desk"
    assert state.energy == pytest.approx(0.7)
    assert state.as_of == moment.isoformat()


def test_generate_life_state_idle_outside_events():
    schedule = WeeklySchedule.default_template("p1")
    moment = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)  # Mon 03:00
    state = generate_life_state(schedule, "p1", moment)
    assert state.activity == "idle"
    assert state.energy == pytest.approx(0.4)


def test_materialize_day():
    schedule = WeeklySchedule.default_template("p1")
    events = materialize_day(schedule, date(2026, 9, 21))
    assert events[0]["date"] == "2026-09-21"
    assert events[0]["start"] == "09:00"
    assert events[0]["end"] == "12:00"
    assert events[0]["activity"] == "working"


def test_degraded_life_state_shape():
    state = LifeState.degraded("p1", as_of="2026-09-21T00:00:00+00:00")
    assert state.to_dict() == {
        "persona_id": "p1",
        "activity": "",
        "energy": 0.0,
        "scene": "",
        "summary": "",
        "as_of": "2026-09-21T00:00:00+00:00",
    }
