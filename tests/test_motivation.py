"""T3 acceptance tests: motivation fusion, open threads, audit, outcomes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.contract import ContractV1, QuotaView
from core.life_state import WeeklySchedule
from core.motivation import (
    build_quota,
    expression_hints,
    fuse_motivation,
    relationship_mode,
    sanitize_thread_title,
    time_window,
)
from core.relationship import STAGE_STRANGER, RelationshipState

UMO = "aiocqhttp:FriendMessage:67890"
GROUP_UMO = "aiocqhttp:GroupMessage:67890"


def _moment(day: int = 21, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def _clock(hour: int = 10):
    return lambda: _moment(hour=hour)


# -- pure scoring (deterministic) -----------------------------------------
def test_fuse_motivation_is_deterministic():
    kwargs = {
        "moment": _moment(hour=10),
        "stage": "熟悉",
        "bond": False,
        "unanswered_streak": 0,
        "activity": "working",
        "energy": 0.7,
        "scene": "desk",
        "open_threads": ("周末电影推荐未给", "论文还没改"),
        "allow": True,
    }
    first = fuse_motivation(**kwargs)
    second = fuse_motivation(**kwargs)
    assert first == second
    assert first.selected is not None
    assert first.selected == first.candidates[0]
    # Recency: the newest thread wins, then scores are non-increasing.
    assert first.candidates[0].key == "open_thread:0"
    scores = [candidate.score for candidate in first.candidates]
    assert scores == sorted(scores, reverse=True)
    assert first.adopted is True
    assert first.blocked_reason == ""


def test_open_thread_outranks_life_and_time():
    result = fuse_motivation(
        moment=_moment(hour=10),
        stage="熟悉",
        activity="working",
        energy=0.7,
        open_threads=("周末电影推荐未给",),
    )
    ordered = [candidate.key for candidate in result.candidates]
    assert ordered[0] == "open_thread:0"
    assert "life_event" in ordered
    assert any(key.startswith("time:") for key in ordered)


def test_streak_and_quota_block_adoption_but_stay_traceable():
    blocked_by_streak = fuse_motivation(
        moment=_moment(hour=10), activity="working", unanswered_streak=5
    )
    assert blocked_by_streak.adopted is False
    assert blocked_by_streak.blocked_reason == "unanswered_streak"
    assert blocked_by_streak.score > 0.0  # still reported for audit

    blocked_by_quota = fuse_motivation(moment=_moment(hour=10), allow=False)
    assert blocked_by_quota.adopted is False
    assert blocked_by_quota.blocked_reason == "quota"


def test_scores_are_clamped_and_rounded():
    result = fuse_motivation(moment=_moment(hour=10), stage="亲密", energy=1.0, bond=True)
    assert result.candidates
    for candidate in result.candidates:
        assert 0.0 <= candidate.score <= 1.0
        assert round(candidate.score, 4) == candidate.score


# -- open-thread labels (short only) --------------------------------------
def test_sanitize_thread_title_collapses_and_truncates():
    assert sanitize_thread_title("  周末\n电影   推荐未给  ") == "周末 电影 推荐未给"
    long_label = sanitize_thread_title("x" * 200)
    assert len(long_label) <= 40
    assert long_label.endswith("…")


def test_upsert_open_thread_stores_short_label(store):
    row = store.upsert_open_thread("t1", UMO, "p1", "  周末\n电影推荐未给  ")
    assert row["title"] == "周末 电影推荐未给"
    resolved = store.resolve_open_threads(UMO, "p1")
    assert [item["title"] for item in resolved] == ["周末 电影推荐未给"]


# -- derived hints ---------------------------------------------------------
def test_time_window_buckets():
    assert time_window(8) == ("morning", "早上")
    assert time_window(12) == ("midday", "中午")
    assert time_window(20) == ("evening", "晚上")
    assert time_window(2) == ("night", "深夜")


def test_expression_hints_by_stage_and_streak():
    intimate = expression_hints("亲密", bond=True)
    assert intimate == {"address": "你", "warmth": 1.0, "proactive_bias": 0.2}
    stranger = expression_hints(STAGE_STRANGER)
    assert stranger["address"] == "您"
    assert stranger["proactive_bias"] == pytest.approx(-0.2)
    # Positive bias is damped by the unanswered streak; negative is untouched.
    damped = expression_hints("亲密", unanswered_streak=1)
    assert damped["proactive_bias"] == pytest.approx(0.1)
    assert expression_hints(STAGE_STRANGER, unanswered_streak=1)["proactive_bias"] == pytest.approx(
        -0.2
    )


def test_relationship_mode():
    assert relationship_mode("熟悉") == "放松"
    assert relationship_mode(STAGE_STRANGER) == "疏离"
    assert relationship_mode("熟悉", bond=True) == "默契"


def test_build_quota():
    assert build_quota(0, 0) == {"hourly_remaining": 1, "daily_remaining": 3, "allow": True}
    assert build_quota(3, 1) == {"hourly_remaining": 0, "daily_remaining": 0, "allow": False}
    assert build_quota(1, 1)["allow"] is False


# -- contract: fully populated context ------------------------------------
async def test_contract_context_full_v1(store):
    store.upsert_open_thread("t1", UMO, "p1", "周末电影推荐未给", now=_moment(hour=8))
    store.upsert_open_thread("t2", UMO, "p1", "论文还没改", now=_moment(hour=9))
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.42,
            stage="熟悉",
            updated_at=_moment().isoformat(),
        )
    )
    contract = ContractV1(store, schedule=WeeklySchedule.default_template("p1"), clock=_clock(10))
    ctx = await contract.get_proactive_context(UMO, persona_id="p1")

    assert ctx["api_version"] == 1
    assert ctx["life_state"]["activity"] == "working"
    assert ctx["relationship"] == {
        "stage": "熟悉",
        "affinity": pytest.approx(0.42),
        "bond": False,
        "mode": "放松",
    }
    assert ctx["expression_hints"]["address"] == "你"
    assert ctx["open_threads"] == ["论文还没改", "周末电影推荐未给"]
    assert ctx["motivation"]["candidates"][0]["key"].startswith("open_thread")
    assert ctx["motivation"]["reason"]
    assert ctx["unanswered_streak"] == 0
    assert ctx["quota"] == build_quota(0, 0)
    assert ctx["degraded"] is False


async def test_contract_context_is_pure_read(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.42,
            stage="熟悉",
            updated_at=_moment().isoformat(),
        )
    )
    contract = ContractV1(store, schedule=WeeklySchedule.default_template("p1"), clock=_clock(10))
    before = store.list_motivation_log("p1")
    first = await contract.get_proactive_context(UMO, persona_id="p1")
    second = await contract.get_proactive_context(UMO, persona_id="p1")
    assert first == second
    assert store.list_motivation_log("p1") == before  # no audit side effect


async def test_contract_group_isolated_context(store):
    store.upsert_open_thread("t1", UMO, "p1", "私聊话题")
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.7,
            stage="亲近",
            updated_at=_moment().isoformat(),
        )
    )
    contract = ContractV1(store, clock=_clock(10))
    ctx = await contract.get_proactive_context(GROUP_UMO, persona_id="p1")
    assert ctx["open_threads"] == []
    assert ctx["unanswered_streak"] == 0
    assert ctx["relationship"]["stage"] == STAGE_STRANGER
    assert ctx["motivation"]["candidates"]


# -- contract: outcome receipt --------------------------------------------
async def test_on_proactive_outcome_idempotent_by_bucket(store):
    contract = ContractV1(store, clock=_clock(10))
    first = await contract.on_proactive_outcome(
        UMO, sent=True, reason_code="time_window", persona_id="p1"
    )
    replay = await contract.on_proactive_outcome(
        UMO, sent=True, reason_code="time_window", persona_id="p1"
    )
    assert first["applied"] is True
    assert replay["duplicate"] is True
    assert replay["applied"] is False

    dynamics = store.get_interaction_dynamics("p1", "67890")
    assert dynamics.proactive_sent == 1
    assert dynamics.unanswered_streak == 1

    # A distinct reason_code is a distinct receipt.
    other = await contract.on_proactive_outcome(
        UMO, sent=True, reason_code="open_thread", persona_id="p1"
    )
    assert other["applied"] is True
    assert store.get_interaction_dynamics("p1", "67890").proactive_sent == 2


async def test_on_proactive_outcome_explicit_event_id(store):
    contract = ContractV1(store, clock=_clock(10))
    await contract.on_proactive_outcome(
        UMO, sent=False, reason_code="quota", event_id="evt-1", persona_id="p1"
    )
    replay = await contract.on_proactive_outcome(
        UMO, sent=False, reason_code="quota", event_id="evt-1", persona_id="p1"
    )
    assert replay["duplicate"] is True
    fresh = await contract.on_proactive_outcome(
        UMO, sent=False, reason_code="quota", event_id="evt-2", persona_id="p1"
    )
    assert fresh["applied"] is True
    # Unsent outcomes never inflate the sent count.
    assert store.get_interaction_dynamics("p1", "67890").proactive_sent == 0


async def test_on_proactive_outcome_group_is_isolated(store):
    contract = ContractV1(store, clock=_clock(10))
    result = await contract.on_proactive_outcome(GROUP_UMO, sent=True, reason_code="x")
    assert result["isolated"] is True
    assert result["applied"] is False
    assert store.get_interaction_dynamics("default", "group:67890").proactive_sent == 0


async def test_quota_consumed_and_streak_grows(store):
    contract = ContractV1(store, clock=_clock(10))
    await contract.on_proactive_outcome(UMO, sent=True, reason_code="time_window", persona_id="p1")
    ctx = await contract.get_proactive_context(UMO, persona_id="p1")
    assert ctx["quota"]["daily_remaining"] == 2
    assert ctx["quota"]["hourly_remaining"] == 0
    assert ctx["quota"]["allow"] is False
    assert ctx["unanswered_streak"] == 1


async def test_motivation_log_audit_columns(store):
    contract = ContractV1(store, clock=_clock(10))
    await contract.on_proactive_outcome(UMO, sent=True, reason_code="time_window", persona_id="p1")
    sent_rows = store.list_motivation_log("p1")
    assert sent_rows[0]["adopted"] == 1
    assert sent_rows[0]["reason_code"] == "time_window"
    assert sent_rows[0]["receipt_key"]
    assert sent_rows[0]["candidates_json"] == "[]"

    await contract.on_proactive_outcome(
        UMO,
        sent=False,
        reason_code="blocked_demo",
        event_id="evt-block",
        persona_id="p1",
        now=_moment(hour=10, minute=5),
    )
    blocked = store.list_motivation_log("p1")[0]
    assert blocked["adopted"] == 0
    assert blocked["blocked_reason"] == "blocked_demo"


# -- per-field fallback ----------------------------------------------------
async def test_context_fields_fallback_when_storage_fails(store):
    contract = ContractV1(store, clock=_clock(10))
    store.close()
    ctx = await contract.get_proactive_context(UMO, persona_id="p1")
    assert ctx["api_version"] == 1
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
    assert ctx["open_threads"] == []
    assert ctx["unanswered_streak"] == 0
    assert ctx["quota"] == QuotaView().to_dict()
    assert ctx["motivation"]["blocked_reason"] == "quota"
    assert ctx["degraded"] is True


def test_schema_v3_audit_columns(store):
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(motivation_log)")}
    assert {
        "umo",
        "user_id",
        "candidates_json",
        "selected_reason",
        "adopted",
        "blocked_reason",
        "reason_code",
        "receipt_key",
    } <= columns
