"""Phase 3-A (v1.6): group understanding, membership isolation, gate, privacy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.contract import ContractV1
from core.group import (
    REASON_COOLDOWN,
    REASON_DISABLED,
    REASON_GROUP_BUSY,
    REASON_HOURLY_LIMIT,
    REASON_OK,
    activity_level,
    member_key_for,
)
from core.store import Store

GROUP_UMO = "aiocqhttp:GroupMessage:10001"
GROUP_UMO_B = "aiocqhttp:GroupMessage:20002"
PRIVATE_UMO = "webchat:FriendMessage:webchat!u1!private"
BASE = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _contract(config=None, now=BASE):
    store = Store.open(":memory:")
    contract = ContractV1(store, config=config or {}, clock=lambda: now)
    return store, contract


def test_member_key_is_local_and_group_scoped():
    assert member_key_for("group:10001", "42") == "group:10001#42"
    assert member_key_for("group:10001", "42") != member_key_for("group:20002", "42")
    assert member_key_for("group:10001", None) == ""
    assert member_key_for("group:10001", "x" * 300).count("#") == 1
    assert len(member_key_for("group:10001", "x" * 300)) <= 80


def test_activity_level_buckets():
    assert activity_level(0, 120) == "low"
    assert activity_level(40, 120) == "medium"
    assert activity_level(120, 120) == "high"


async def test_group_context_private_is_isolated():
    _, contract = _contract()
    ctx = await contract.get_group_context(PRIVATE_UMO)
    assert ctx["is_group"] is False
    assert ctx["isolated"] is True
    assert ctx["group"] is None


async def test_record_group_activity_private_is_noop():
    store, contract = _contract()
    result = await contract.record_group_activity(PRIVATE_UMO, member_id="u1", topic="话题")
    assert result["applied"] is False
    assert result["isolated"] is True
    assert store.get_group_activity(PRIVATE_UMO) is None


async def test_record_group_activity_counts_topic_and_member():
    store, contract = _contract()
    await contract.record_group_activity(
        GROUP_UMO, member_id="42", topic="  周末  爬山  ", now=BASE
    )
    await contract.record_group_activity(GROUP_UMO, member_id="42", now=BASE)
    await contract.record_group_activity(GROUP_UMO, member_id="43", now=BASE)

    row = store.get_group_activity(GROUP_UMO)
    assert row["message_count"] == 3
    assert row["hour_count"] == 3
    assert row["day_count"] == 3
    assert row["topic"] == "周末 爬山"
    assert store.count_group_members(GROUP_UMO) == 2

    ctx = await contract.get_group_context(GROUP_UMO, member_id="42")
    assert ctx["is_group"] is True
    assert ctx["group"]["topic"] == "周末 爬山"
    assert ctx["group"]["topic_age_min"] == 0.0
    assert ctx["group"]["last_activity"] == BASE.isoformat()
    assert ctx["group"]["member_count"] == 2
    assert ctx["member"] == {
        "member_key": "group:10001#42",
        "familiarity": 2,
        "is_known": True,
    }


async def test_group_members_do_not_aggregate_across_groups():
    store, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, member_id="42", now=BASE)
    await contract.record_group_activity(GROUP_UMO, member_id="42", now=BASE)
    await contract.record_group_activity(GROUP_UMO_B, member_id="42", now=BASE)

    a = await contract.get_group_context(GROUP_UMO, member_id="42")
    b = await contract.get_group_context(GROUP_UMO_B, member_id="42")
    assert a["member"]["member_key"] == "group:10001#42"
    assert b["member"]["member_key"] == "group:20002#42"
    assert a["member"]["familiarity"] == 2
    assert b["member"]["familiarity"] == 1


async def test_participation_ok_then_cooldown():
    store, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, now=BASE)

    first = await contract.get_group_context(GROUP_UMO)
    assert first["participation"]["allow"] is True
    assert first["participation"]["reason"] == REASON_OK

    second = await contract.get_group_context(GROUP_UMO)
    assert second["participation"]["allow"] is False
    assert second["participation"]["reason"] == REASON_COOLDOWN
    assert second["participation"]["cooldown_remaining_sec"] == 90

    # after the gap elapses the slot frees up again
    later = ContractV1(
        store, config={}, clock=lambda: BASE + timedelta(minutes=2)
    )
    third = await later.get_group_context(GROUP_UMO)
    assert third["participation"]["allow"] is True


async def test_participation_hourly_limit():
    _, contract = _contract(config={"group": {"min_reply_gap_sec": 0, "hourly_limit": 1}})
    await contract.record_group_activity(GROUP_UMO, now=BASE)

    first = await contract.get_group_context(GROUP_UMO)
    assert first["participation"]["allow"] is True
    assert first["participation"]["hourly_remaining"] == 0

    second = await contract.get_group_context(GROUP_UMO)
    assert second["participation"]["allow"] is False
    assert second["participation"]["reason"] == REASON_HOURLY_LIMIT


async def test_participation_group_busy():
    _, contract = _contract(config={"group": {"busy_group_threshold": 3}})
    for _ in range(3):
        await contract.record_group_activity(GROUP_UMO, now=BASE)

    ctx = await contract.get_group_context(GROUP_UMO)
    assert ctx["group"]["activity_level"] == "high"
    assert ctx["participation"]["allow"] is False
    assert ctx["participation"]["reason"] == REASON_GROUP_BUSY


async def test_participation_disabled_reports_disabled():
    _, contract = _contract(config={"group": {"participation_enabled": False}})
    await contract.record_group_activity(GROUP_UMO, now=BASE)
    ctx = await contract.get_group_context(GROUP_UMO)
    assert ctx["is_group"] is True
    assert ctx["participation"]["allow"] is False
    assert ctx["participation"]["reason"] == REASON_DISABLED


async def test_group_disabled_fails_closed():
    store, contract = _contract(config={"group": {"enabled": False}})
    recorded = await contract.record_group_activity(GROUP_UMO, member_id="42", now=BASE)
    assert recorded["isolated"] is True and recorded["applied"] is False
    assert store.get_group_activity(GROUP_UMO) is None

    ctx = await contract.get_group_context(GROUP_UMO)
    assert ctx["is_group"] is True and ctx["isolated"] is True

    proactive = await contract.get_proactive_context(GROUP_UMO)
    assert "group" not in proactive
    assert "participation" not in proactive


async def test_proactive_context_group_has_group_keys_and_no_private_leak():
    _, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, member_id="42", now=BASE)
    ctx = await contract.get_proactive_context(GROUP_UMO)

    assert ctx["group"]["member_count"] == 1
    assert "participation" in ctx
    # private-only keys stay absent for groups
    assert "person_id" not in ctx
    assert "life_detail" not in ctx


async def test_proactive_context_read_does_not_consume_slot():
    _, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, now=BASE)
    first = await contract.get_proactive_context(GROUP_UMO)
    second = await contract.get_proactive_context(GROUP_UMO)
    assert first["participation"]["allow"] is True
    assert second["participation"]["allow"] is True
    # the decision endpoint is get_group_context, which does consume
    decided = await contract.get_group_context(GROUP_UMO)
    assert decided["participation"]["allow"] is True
    again = await contract.get_group_context(GROUP_UMO)
    assert again["participation"]["allow"] is False
