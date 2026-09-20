"""tcompanion_core — Phase 1 foundation package.

Frozen contract v1 + SQLite persistence + simplified LifeState/Schedule.
No message bodies are ever persisted (see ``docs/CONTRACT.md``).
"""

from __future__ import annotations

from .contract import CONTRACT_API_VERSION, ContractV1
from .life_state import LifeState, ScheduleEvent, WeeklySchedule
from .store import Store

__all__ = [
    "CONTRACT_API_VERSION",
    "ContractV1",
    "LifeState",
    "ScheduleEvent",
    "Store",
    "WeeklySchedule",
]
