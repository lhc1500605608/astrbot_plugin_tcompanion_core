from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    assert info["capabilities"]["life_line"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


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


# -- open threads (v1.2 · Phase 2-B) --------------------------------------
UMO = "aiocqhttp:FriendMessage:67890"
GROUP_UMO = "aiocqhttp:GroupMessage:67890"


async def test_open_threads_capability_bit(store):
    contract = ContractV1(store)
    info = await contract.get_contract_info()
    assert info["capabilities"]["open_threads_followup"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


async def test_record_open_thread_sanitizes_and_dedupes(store):
    contract = ContractV1(store, clock=_fixed_clock())
    first = await contract.record_open_thread(
        UMO, label="  周末\n电影推荐未给  ", kind="commitment", confidence=0.8, source="kanjyou:rule"
    )
    assert first["applied"] is True
    assert first["label"] == "周末 电影推荐未给"
    assert first["status"] == "open"

    # same kind|label -> same thread, recency bumped, still one row
    second = await contract.record_open_thread(
        UMO, label="周末 电影推荐未给", kind="commitment"
    )
    assert second["thread_id"] == first["thread_id"]
    assert len(store.list_open_thread_details(UMO, "default")) == 1


async def test_record_open_thread_truncates_long_label(store):
    contract = ContractV1(store, clock=_fixed_clock())
    result = await contract.record_open_thread(UMO, label="长" * 200, kind="plan")
    assert len(result["label"]) <= 40
    stored = store.list_open_thread_details(UMO, "default")[0]
    assert len(stored["title"]) <= 40


async def test_get_open_threads_shape_and_limit(store):
    contract = ContractV1(store, clock=_fixed_clock())
    for index, kind in enumerate(("commitment", "plan", "topic", "commitment")):
        await contract.record_open_thread(UMO, label=f"话题{index}", kind=kind)
    items = await contract.get_open_threads(UMO, limit=3)
    assert len(items) == 3
    assert set(items[0]) == {
        "thread_id",
        "label",
        "kind",
        "status",
        "last_seen",
        "followup_count",
        "confidence",
    }


async def test_close_and_mark_followup_roundtrip(store):
    contract = ContractV1(store, clock=_fixed_clock())
    recorded = await contract.record_open_thread(UMO, label="明天发方案", kind="commitment")
    thread_id = recorded["thread_id"]

    marked = await contract.mark_thread_followup(UMO, thread_id)
    assert marked["updated"] is True
    assert marked["followup_count"] == 1

    closed = await contract.close_open_thread(UMO, thread_id, reason="answered")
    assert closed["closed"] is True
    active = await contract.get_open_threads(UMO)
    assert active == []
    assert await contract.mark_thread_followup(UMO, "missing-id") == {
        "thread_id": "missing-id",
        "updated": False,
        "followup_count": 0,
        "last_followup_ts": "",
        "isolated": False,
        "reason": "not_found",
        "degraded": False,
    }


async def test_open_thread_group_scopes_are_isolated(store):
    contract = ContractV1(store, clock=_fixed_clock())
    recorded = await contract.record_open_thread(GROUP_UMO, label="私聊话题", kind="topic")
    assert recorded["isolated"] is True
    assert recorded["applied"] is False
    assert await contract.get_open_threads(GROUP_UMO) == []
    assert (await contract.close_open_thread(GROUP_UMO, "x"))["isolated"] is True
    assert (await contract.mark_thread_followup(GROUP_UMO, "x"))["isolated"] is True
    assert store.list_open_thread_details(GROUP_UMO) == []


async def test_record_open_thread_rejects_unknown_kind(store):
    contract = ContractV1(store, clock=_fixed_clock())
    result = await contract.record_open_thread(UMO, label="话题", kind="not_a_kind")
    assert result["reason"] == "unknown_kind"
    assert result["degraded"] is True
    assert store.list_open_thread_details(UMO) == []


async def test_open_thread_methods_degrade_on_storage_error(store):
    contract = ContractV1(store, clock=_fixed_clock())
    store.close()
    recorded = await contract.record_open_thread(UMO, label="话题", kind="topic")
    assert recorded["degraded"] is True
    assert recorded["reason"] == "storage_error"
    assert await contract.get_open_threads(UMO) == []
    assert (await contract.close_open_thread(UMO, "t"))["degraded"] is True
    assert (await contract.mark_thread_followup(UMO, "t"))["degraded"] is True


async def test_proactive_context_open_thread_details_additive(store):
    contract = ContractV1(
        store, schedule=WeeklySchedule.default_template("p1"), clock=_fixed_clock()
    )
    await contract.record_open_thread(
        UMO, label="论文还没改", kind="plan", confidence=0.8
    )
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["open_threads"] == ["论文还没改"]  # frozen str[] unchanged
    details = ctx["open_thread_details"]
    assert len(details) == 1
    assert details[0]["label"] == "论文还没改"
    assert details[0]["kind"] == "plan"
    assert details[0]["status"] == "open"
    assert details[0]["thread_id"]
    # motivation candidates echo the thread id for receipt bookkeeping
    candidate = next(
        item for item in ctx["motivation"]["candidates"] if item["key"].startswith("open_thread")
    )
    assert candidate["thread_id"] == details[0]["thread_id"]


async def test_group_context_has_empty_open_thread_details(store):
    contract = ContractV1(store, clock=_fixed_clock())
    ctx = await contract.get_proactive_context(GROUP_UMO)
    assert ctx["open_threads"] == []
    assert ctx["open_thread_details"] == []


# -- open-thread lifecycle wiring (TMEAAA-502) ----------------------------
NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
CFG = {
    "open_thread": {
        "enabled": True,
        "max": 20,
        "ttl_days": 3,
        "expire_days": 14,
        "followup_max": 2,
    }
}


def _configured(store, config=None):
    return ContractV1(store, clock=lambda: NOW, config=config if config is not None else CFG)


async def test_read_path_expires_40_day_thread_out_of_candidates(store):
    """Regression (TMEAAA-502): a 40-day-old thread must leave the candidates."""
    store.upsert_open_thread(
        "ancient", UMO, "default", "远古话题", now=NOW - timedelta(days=40)
    )
    contract = _configured(store)

    ctx = await contract.get_proactive_context(UMO)
    assert ctx["open_threads"] == []
    assert ctx["open_thread_details"] == []

    row = store.list_open_thread_details(UMO, "default")[0]
    assert (row["status"], row["closed_reason"]) == ("closed", "expired")


async def test_read_path_marks_stale_and_drops_from_candidates(store):
    store.upsert_open_thread(
        "old", UMO, "default", "搁置话题", now=NOW - timedelta(days=5)
    )
    contract = _configured(store)

    ctx = await contract.get_proactive_context(UMO)
    assert ctx["open_thread_details"] == []

    items = await contract.get_open_threads(UMO)
    assert [item["status"] for item in items] == ["stale"]
    assert store.list_open_thread_details(UMO, "default")[0]["status"] == "stale"


async def test_read_path_enforces_max_open_eviction(store):
    cfg = {"open_thread": {"enabled": True, "max": 2, "ttl_days": 30, "expire_days": 60}}
    for index in range(3):
        store.upsert_open_thread(
            f"t{index}", UMO, "default", f"话题{index}", now=NOW - timedelta(hours=index)
        )
    contract = _configured(store, cfg)

    await contract.get_open_threads(UMO)

    open_rows = store.list_open_thread_details(UMO, "default", status="open")
    assert [row["thread_id"] for row in open_rows] == ["t0", "t1"]
    closed = store.list_open_thread_details(UMO, "default", status="closed")
    assert {row["closed_reason"] for row in closed} == {"superseded"}


async def test_open_thread_disabled_turns_section_off(store):
    """`enabled=false`: all four methods no-op, candidates empty, no writes."""
    cfg = {"open_thread": {"enabled": False}}
    contract = _configured(store, cfg)

    recorded = await contract.record_open_thread(UMO, label="话题", kind="topic")
    assert recorded["applied"] is False
    assert recorded["reason"] == "disabled"
    assert store.list_open_thread_details(UMO) == []

    assert await contract.get_open_threads(UMO) == []
    assert (await contract.close_open_thread(UMO, "t"))["reason"] == "disabled"
    assert (await contract.mark_thread_followup(UMO, "t"))["reason"] == "disabled"

    ctx = await contract.get_proactive_context(UMO)
    assert ctx["open_threads"] == []
    assert ctx["open_thread_details"] == []


async def test_disabled_section_does_not_advance_lifecycle(store):
    store.upsert_open_thread(
        "ancient", UMO, "default", "远古话题", now=NOW - timedelta(days=40)
    )
    contract = _configured(store, {"open_thread": {"enabled": False}})
    await contract.get_proactive_context(UMO)
    row = store.list_open_thread_details(UMO, "default")[0]
    assert (row["status"], row["closed_reason"]) == ("open", "")


async def test_open_thread_config_is_reparsed_on_each_read(store):
    """Hot-reload: editing the injected mapping takes effect without restart."""
    cfg = {"open_thread": {"enabled": True}}
    contract = _configured(store, cfg)
    assert (await contract.record_open_thread(UMO, label="话题", kind="topic"))["applied"]

    cfg["open_thread"]["enabled"] = False
    assert await contract.get_open_threads(UMO) == []
    assert (await contract.record_open_thread(UMO, label="新话题", kind="topic"))[
        "reason"
    ] == "disabled"


async def test_contract_info_exposes_effective_open_thread_config(store):
    contract = _configured(store, {"open_thread": {"max": 7, "ttl_days": 2}})
    info = await contract.get_contract_info()
    assert info["open_thread"] == {
        "enabled": True,
        "max_open": 7,
        "ttl_days": 2,
        "expire_days": 14,
        "followup_max": 2,
    }

