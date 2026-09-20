from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core import db as schema
from core.contract import CONTRACT_API_VERSION, ContractV1
from core.life_state import LifeState, WeeklySchedule
from core.motivation import build_quota
from core.relationship import STAGE_FAMILIAR, STAGE_STRANGER


def _fixed_clock():
    return lambda: datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)  # Monday


async def test_contract_info_shape(store):
    contract = ContractV1(store)
    info = await contract.get_contract_info()
    assert info["api_version"] == CONTRACT_API_VERSION == 1
    assert info["plugin"] == "astrbot_plugin_tcompanion_core"
    assert info["schema_version"] == schema.SCHEMA_VERSION
    assert info["capabilities"]["life_state"] is True
    assert info["capabilities"]["relationship"] is True
    assert info["capabilities"]["motivation"] is True
    assert info["capabilities"]["open_threads"] is True
    assert info["capabilities"]["proactive"] is False


async def test_get_life_state_from_schedule(store):
    contract = ContractV1(
        store, schedule=WeeklySchedule.default_template("p1"), clock=_fixed_clock()
    )
    state = await contract.get_life_state("p1")
    assert state["activity"] == "working"
    assert state["degraded"] is False


async def test_get_life_state_prefers_stored_row(store):
    contract = ContractV1(
        store, schedule=WeeklySchedule.default_template("p1"), clock=_fixed_clock()
    )
    store.upsert_life_state(
        LifeState(
            persona_id="p1",
            activity="resting",
            energy=0.2,
            scene="sofa",
            summary="自定义摘要",
            as_of="2026-09-21T09:30:00+00:00",
        )
    )
    stored = await contract.get_life_state("p1")
    assert stored["summary"] == "自定义摘要"
    assert stored["activity"] == "resting"
    assert stored["degraded"] is False


async def test_get_life_state_empty_persona_returns_none(store):
    contract = ContractV1(store)
    assert await contract.get_life_state("") is None


async def test_get_life_state_without_schedule_is_degraded(store):
    contract = ContractV1(store, clock=_fixed_clock())
    state = await contract.get_life_state("missing")
    assert state["degraded"] is True
    assert state["activity"] == ""


async def test_get_relationship_minimal_structure(store):
    contract = ContractV1(store)
    rel = await contract.get_relationship("umo://a")
    assert rel == {
        "umo": "umo://a",
        "persona_id": None,
        "stage": STAGE_STRANGER,
        "closeness": 0.0,
        "affinity": 0.0,
        "bond": False,
        "degraded": True,
    }


async def test_get_relationship_reads_stored_row(store):
    from core.relationship import RelationshipState

    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="user-1",
            affinity=0.42,
            stage=STAGE_FAMILIAR,
            updated_at="2026-09-21T09:30:00+00:00",
        )
    )
    contract = ContractV1(store)
    rel = await contract.get_relationship("aiocqhttp:FriendMessage:user-1", persona_id="p1")
    assert rel["stage"] == STAGE_FAMILIAR
    assert rel["closeness"] == pytest.approx(0.42)
    assert rel["affinity"] == pytest.approx(0.42)
    assert rel["degraded"] is False


async def test_proactive_context_full_v1_fields(store):
    contract = ContractV1(
        store, schedule=WeeklySchedule.default_template("p1"), clock=_fixed_clock()
    )
    ctx = await contract.get_proactive_context("umo://a", persona_id="p1")
    assert {
        "api_version",
        "life_state",
        "relationship",
        "expression_hints",
        "motivation",
        "open_threads",
        "quota",
        "unanswered_streak",
    } <= set(ctx)
    assert ctx["api_version"] == 1
    assert ctx["quota"] == build_quota(0, 0)
    assert ctx["quota"] == {"hourly_remaining": 1, "daily_remaining": 3, "allow": True}
    assert ctx["life_state"]["activity"] == "working"
    assert ctx["open_threads"] == []
    assert ctx["unanswered_streak"] == 0
    assert ctx["motivation"]["score"] > 0
    assert ctx["degraded"] is False


async def test_proactive_context_without_persona_is_degraded(store):
    contract = ContractV1(store, clock=_fixed_clock())
    ctx = await contract.get_proactive_context("umo://a")
    assert ctx["life_state"] is None
    assert ctx["degraded"] is True


async def test_storage_failure_degrades_not_raises(store):
    contract = ContractV1(store, clock=_fixed_clock())
    store.close()  # simulate storage outage
    info = await contract.get_contract_info()
    assert info["schema_version"] == 0
    state = await contract.get_life_state("p1")
    assert state["degraded"] is True
    rel = await contract.get_relationship("umo://a")
    assert rel["degraded"] is True
