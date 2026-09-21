"""v1.1 acceptance tests: emotion ledger, valence/state, expression decision."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import db as schema
from core import emotion
from core.contract import ContractV1
from core.emotion import (
    EVENT_GRATITUDE,
    EVENT_IGNORED_PROACTIVE,
    EVENT_MISUNDERSTOOD,
    EVENT_SUDDEN_WARMTH,
    EVENT_TYPES,
    EVENT_VALUED_REPLY,
    GROUP_ALLOWED_MODES,
    GROUP_WARMTH_CAP,
    MODE_LOVE,
    MODE_RELAXED,
    STATE_AVOID,
    STATE_CALM,
    STATE_EXPECT,
    STATE_HAPPY,
    STATE_HURT,
    apply_emotion_affinity_delta,
    cap_emotion_delta,
    compute_valence,
    emotion_state,
    expression_for,
)
from core.life_state import LifeState
from core.relationship import STAGE_INTIMATE, RelationshipState

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
UMO = "aiocqhttp:FriendMessage:67890"
GROUP_UMO = "aiocqhttp:GroupMessage:12345"


def _ev(event_type: str, hours_ago: float, delta: float | None = None) -> dict:
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {
        "event_type": event_type,
        "delta": emotion.event_delta(event_type) if delta is None else delta,
        "ts": ts,
        "dedupe_key": f"{event_type}:{hours_ago}",
    }


def _clock():
    return lambda: NOW


# -- pure logic: deltas / valence -----------------------------------------
def test_event_delta_table_matches_plan():
    assert emotion.event_delta(EVENT_VALUED_REPLY) == 0.03
    assert emotion.event_delta(EVENT_IGNORED_PROACTIVE) == -0.02
    assert emotion.event_delta(EVENT_GRATITUDE) == 0.02
    assert emotion.event_delta(EVENT_MISUNDERSTOOD) == -0.03
    assert emotion.event_delta(EVENT_SUDDEN_WARMTH) == 0.02
    assert emotion.event_delta("nope") == 0.0
    assert len(EVENT_TYPES) == 6


def test_cap_emotion_delta_both_signs():
    assert cap_emotion_delta(0.5) == 0.03
    assert cap_emotion_delta(-0.5) == -0.03
    assert cap_emotion_delta(-0.01) == -0.01


def test_valence_half_life_and_window():
    assert compute_valence([_ev(EVENT_VALUED_REPLY, 0)], NOW) == pytest.approx(0.03)
    assert compute_valence([_ev(EVENT_VALUED_REPLY, 24)], NOW) == pytest.approx(0.015)
    assert compute_valence([_ev(EVENT_VALUED_REPLY, 48)], NOW) == pytest.approx(0.0075)
    # outside the 72h window (and future stamps) are ignored
    assert compute_valence([_ev(EVENT_VALUED_REPLY, 73)], NOW) == 0.0
    assert compute_valence([_ev(EVENT_VALUED_REPLY, -1)], NOW) == 0.0


def test_valence_is_clamped():
    events = [_ev(EVENT_VALUED_REPLY, 0) for _ in range(100)]
    assert compute_valence(events, NOW) == 1.0


# -- pure logic: state priority -------------------------------------------
def test_state_priority_order():
    assert emotion_state([_ev(EVENT_MISUNDERSTOOD, 1)], now=NOW) == STATE_HURT
    assert emotion_state([_ev(EVENT_VALUED_REPLY, 1)], now=NOW, unanswered_streak=2) == STATE_AVOID
    assert (
        emotion_state(
            [_ev(EVENT_IGNORED_PROACTIVE, 1), _ev(EVENT_IGNORED_PROACTIVE, 2)], now=NOW
        )
        == STATE_AVOID
    )
    assert emotion_state([], now=NOW) == STATE_CALM


def test_state_expect_and_happy():
    expect = [_ev(EVENT_GRATITUDE, 1) for _ in range(8)]  # valence 0.16
    assert emotion_state(expect, now=NOW) == STATE_EXPECT
    # same valence but 13h old: no positive event inside 12h -> 开心 branch
    happy = [_ev(EVENT_GRATITUDE, 13) for _ in range(20)]  # 0.40 * 0.5^(13/24)
    assert compute_valence(happy, NOW) >= 0.25
    assert emotion_state(happy, now=NOW) == STATE_HAPPY


def test_hurt_from_deep_negative_valence():
    # No recent misunderstood event, but valence <= -0.35 still reads as 受伤.
    events = [_ev(EVENT_IGNORED_PROACTIVE, 0) for _ in range(18)]
    assert compute_valence(events, NOW) <= -0.35
    assert emotion_state(events, now=NOW) == STATE_HURT


# -- pure logic: affinity application --------------------------------------
def test_emotion_affinity_caps_and_floor():
    assert apply_emotion_affinity_delta(0.03, daily_positive_used=0.0) == 0.03
    assert apply_emotion_affinity_delta(0.03, daily_positive_used=0.09) == pytest.approx(0.01)
    assert apply_emotion_affinity_delta(0.03, daily_positive_used=0.10) == 0.0
    assert apply_emotion_affinity_delta(-0.02, daily_negative_used=0.0, affinity=1.0) == -0.02
    assert apply_emotion_affinity_delta(-0.02, daily_negative_used=0.05, affinity=1.0) == pytest.approx(
        -0.01
    )
    assert apply_emotion_affinity_delta(-0.02, daily_negative_used=0.06, affinity=1.0) == 0.0
    assert apply_emotion_affinity_delta(-0.02, daily_negative_used=0.0, affinity=0.01) == -0.01


# -- pure logic: expression ------------------------------------------------
def test_expression_priority_private():
    assert expression_for(state=STATE_AVOID)["mode"] == "回避"
    assert expression_for(unanswered_streak=2)["mode"] == "回避"
    assert expression_for(state=STATE_HURT)["mode"] == "受伤"
    love = expression_for(stage=STAGE_INTIMATE, bond=True, valence=0.1)
    assert love["mode"] == MODE_LOVE
    assert expression_for(stage="亲近", valence=-0.01)["mode"] == "亲近"
    assert expression_for(stage="熟悉", valence=0.0)["mode"] == "温暖"
    assert expression_for(stage="陌生", valence=0.3, energy=0.9)["mode"] == "活泼"
    assert expression_for(stage="陌生")["mode"] == MODE_RELAXED


def test_expression_group_suppression():
    for stage, bond, state in (
        (STAGE_INTIMATE, True, STATE_CALM),
        ("亲近", False, STATE_CALM),
        ("陌生", False, STATE_HURT),
        ("陌生", False, STATE_AVOID),
    ):
        decision = expression_for(
            state=state, stage=stage, bond=bond, is_group=True, unanswered_streak=3
        )
        assert decision["mode"] in GROUP_ALLOWED_MODES
        assert decision["style_hints"]["warmth"] <= GROUP_WARMTH_CAP


# -- store -----------------------------------------------------------------
def test_store_records_event_and_ledger(store):
    result = store.apply_emotion_event(
        "p1", "u1", event_id="k1", event_type=EVENT_VALUED_REPLY, delta=0.03, now=NOW
    )
    assert result["applied"] is True
    assert result["delta"] == pytest.approx(0.03)
    assert result["state"].affinity == pytest.approx(0.03)
    row = store.list_emotion_events("p1", "u1")[0]
    assert row["event_type"] == EVENT_VALUED_REPLY
    ledger = store.list_affinity_ledger("p1", "u1")[0]
    assert ledger["event_type"] == EVENT_VALUED_REPLY


def test_store_event_is_idempotent(store):
    store.apply_emotion_event(
        "p1", "u1", event_id="k1", event_type=EVENT_VALUED_REPLY, delta=0.03, now=NOW
    )
    again = store.apply_emotion_event(
        "p1", "u1", event_id="k1", event_type=EVENT_GRATITUDE, delta=0.02, now=NOW
    )
    assert again["duplicate"] is True
    assert again["applied"] is False
    assert len(store.list_emotion_events("p1", "u1")) == 1
    assert store.get_relationship_state("p1", "u1").affinity == pytest.approx(0.03)


def test_store_daily_positive_cap(store):
    for i in range(4):
        store.apply_emotion_event(
            "p1", "u1", event_id=f"k{i}", event_type=EVENT_VALUED_REPLY, delta=0.03, now=NOW
        )
    state = store.get_relationship_state("p1", "u1")
    assert state.affinity == pytest.approx(0.10)


def test_store_daily_negative_cap_and_floor(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1", user_id="u1", affinity=0.5, updated_at=NOW.isoformat()
        )
    )
    for i in range(4):
        store.apply_emotion_event(
            "p1",
            "u1",
            event_id=f"n{i}",
            event_type=EVENT_IGNORED_PROACTIVE,
            delta=-0.02,
            now=NOW,
        )
    assert store.get_relationship_state("p1", "u1").affinity == pytest.approx(0.44)

    store.save_relationship_state(
        RelationshipState(
            persona_id="p1", user_id="u2", affinity=0.01, updated_at=NOW.isoformat()
        )
    )
    floor = store.apply_emotion_event(
        "p1", "u2", event_id="f1", event_type=EVENT_MISUNDERSTOOD, delta=-0.03, now=NOW
    )
    assert floor["delta"] == pytest.approx(-0.01)
    assert store.get_relationship_state("p1", "u2").affinity == 0.0


def test_store_event_keeps_canonical_delta_when_affinity_capped(store):
    for i in range(4):
        store.apply_emotion_event(
            "p1", "u1", event_id=f"k{i}", event_type=EVENT_VALUED_REPLY, delta=0.03, now=NOW
        )
    suppressed = store.apply_emotion_event(
        "p1", "u1", event_id="k9", event_type=EVENT_GRATITUDE, delta=0.02, now=NOW
    )
    assert suppressed["applied"] is False
    assert suppressed["event_delta"] == pytest.approx(0.02)


# -- contract: record_emotion_event ---------------------------------------
async def test_record_emotion_event_private(store):
    contract = ContractV1(store, clock=_clock())
    out = await contract.record_emotion_event(UMO, event_type=EVENT_VALUED_REPLY)
    assert out["applied"] is True
    assert out["duplicate"] is False
    assert out["isolated"] is False
    assert out["event"]["delta"] == pytest.approx(0.03)
    assert out["affinity"] == pytest.approx(0.03)
    assert out["degraded"] is False


async def test_record_emotion_event_group_isolated(store):
    contract = ContractV1(store, clock=_clock())
    out = await contract.record_emotion_event(GROUP_UMO, event_type=EVENT_VALUED_REPLY)
    assert out["isolated"] is True
    assert out["applied"] is False
    assert store.list_emotion_events("", "group:12345") == []


async def test_record_emotion_event_unknown_type_fails_closed(store):
    contract = ContractV1(store, clock=_clock())
    out = await contract.record_emotion_event(UMO, event_type="not_a_type")
    assert out["applied"] is False
    assert out["degraded"] is True
    assert out["reason"] == "unknown_event_type"


async def test_record_emotion_event_default_dedupe_is_daily(store):
    contract = ContractV1(store, clock=_clock())
    first = await contract.record_emotion_event(UMO, event_type=EVENT_GRATITUDE)
    second = await contract.record_emotion_event(UMO, event_type=EVENT_GRATITUDE)
    assert first["applied"] is True
    assert second["duplicate"] is True
    assert second["applied"] is False


async def test_proactive_receipts_share_one_key(store):
    contract = ContractV1(store, clock=_clock())
    replied = await contract.record_emotion_event(
        UMO, event_type=EVENT_VALUED_REPLY, dedupe_key="proactive:100"
    )
    ignored = await contract.record_emotion_event(
        UMO, event_type=EVENT_IGNORED_PROACTIVE, dedupe_key="proactive:100"
    )
    assert replied["applied"] is True
    assert ignored["duplicate"] is True
    assert ignored["applied"] is False
    assert store.get_relationship_state("default", "67890").affinity == pytest.approx(0.03)


async def test_record_emotion_event_storage_error_degrades(store):
    contract = ContractV1(store, clock=_clock())
    store.close()
    out = await contract.record_emotion_event(UMO, event_type=EVENT_GRATITUDE)
    assert out["applied"] is False
    assert out["degraded"] is True
    assert out["reason"] == "storage_error"


# -- contract: get_emotion_context / expression_decision -------------------
async def test_get_emotion_context_private(store):
    contract = ContractV1(store, clock=_clock())
    await contract.record_emotion_event(UMO, event_type=EVENT_MISUNDERSTOOD)
    ctx = await contract.get_emotion_context(UMO)
    assert ctx["state"] == STATE_HURT
    assert ctx["valence"] < 0
    assert ctx["last_event"] == EVENT_MISUNDERSTOOD
    assert ctx["recent"][0]["event_type"] == EVENT_MISUNDERSTOOD
    assert set(ctx["recent"][0]) == {"event_type", "delta", "ts"}
    assert ctx["degraded"] is False


async def test_get_emotion_context_group_is_degraded(store):
    contract = ContractV1(store, clock=_clock())
    ctx = await contract.get_emotion_context(GROUP_UMO)
    assert ctx["state"] == "平静"
    assert ctx["valence"] == 0.0
    assert ctx["recent"] == []
    assert ctx["degraded"] is True


async def test_expression_decision_private_avoid(store):
    contract = ContractV1(store, clock=_clock())
    store.record_proactive_outcome("default", "67890", sent=True, now=NOW)
    store.record_proactive_outcome("default", "67890", sent=True, now=NOW)
    decision = await contract.expression_decision(UMO)
    assert decision["api_version"] == 1
    assert decision["mode"] == "回避"
    assert decision["style_hints"]["proactive_bias"] < 0
    assert decision["degraded"] is False


async def test_expression_decision_group_never_intimate(store):
    contract = ContractV1(store, clock=_clock())
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.9,
            stage=STAGE_INTIMATE,
            bond=True,
            updated_at=NOW.isoformat(),
        )
    )
    decision = await contract.expression_decision(GROUP_UMO)
    assert decision["mode"] in GROUP_ALLOWED_MODES
    assert decision["style_hints"]["warmth"] <= GROUP_WARMTH_CAP


async def test_expression_decision_degraded_on_storage_failure(store):
    contract = ContractV1(store, clock=_clock())
    store.close()
    decision = await contract.expression_decision(UMO)
    assert decision["mode"] == MODE_RELAXED
    assert decision["degraded"] is True


# -- contract: get_proactive_context --------------------------------------
async def test_proactive_context_exposes_emotion_and_expression(store):
    contract = ContractV1(store, clock=_clock())
    await contract.record_emotion_event(UMO, event_type=EVENT_VALUED_REPLY)
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["api_version"] == 1
    assert ctx["emotion_state"]["state"] in emotion.EMOTION_STATES
    assert ctx["emotion_state"]["last_event"] == EVENT_VALUED_REPLY
    assert ctx["expression"]["mode"] in emotion.EXPRESSION_MODES
    assert "style_hints" in ctx["expression"]


async def test_proactive_context_group_has_no_private_emotion(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.9,
            stage=STAGE_INTIMATE,
            bond=True,
            updated_at=NOW.isoformat(),
        )
    )
    contract = ContractV1(store, clock=_clock())
    ctx = await contract.get_proactive_context(GROUP_UMO)
    assert ctx["emotion_state"] is None
    assert ctx["expression"]["mode"] in GROUP_ALLOWED_MODES
    assert ctx["relationship"]["bond"] is False


async def test_negative_emotion_only_dampens_motivation(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1", user_id="67890", affinity=0.0, updated_at=NOW.isoformat()
        )
    )
    contract = ContractV1(store, clock=_clock())
    neutral = await contract.get_proactive_context(UMO, persona_id="p1")
    for i in range(2):
        await contract.record_emotion_event(
            UMO, event_type=EVENT_IGNORED_PROACTIVE, dedupe_key=f"proactive:{i}"
        )
    negative = await contract.get_proactive_context(UMO, persona_id="p1")
    assert neutral["emotion_state"]["state"] == "平静"
    assert negative["emotion_state"]["state"] == STATE_AVOID
    assert negative["motivation"]["score"] < neutral["motivation"]["score"]

    # a positive emotion never boosts the score (damping is <= 1.0 always)
    umo2 = "aiocqhttp:FriendMessage:22222"
    store.save_relationship_state(
        RelationshipState(
            persona_id="p2", user_id="22222", affinity=0.0, updated_at=NOW.isoformat()
        )
    )
    neutral2 = await contract.get_proactive_context(umo2, persona_id="p2")
    for i in range(8):  # valence 0.16 -> 期待 (a positive state)
        await contract.record_emotion_event(
            umo2, event_type=EVENT_VALUED_REPLY, dedupe_key=f"reply:{i}"
        )
    positive2 = await contract.get_proactive_context(umo2, persona_id="p2")
    assert positive2["emotion_state"]["state"] == STATE_EXPECT
    assert positive2["motivation"]["score"] == neutral2["motivation"]["score"]


# -- schema v4 -------------------------------------------------------------
def test_schema_v4_tables_and_columns(store):
    assert store.schema_version == 4
    assert "emotion_events" in store.table_names()
    cols = {row[1] for row in store.connection.execute("PRAGMA table_info(affinity_ledger)")}
    assert "event_type" in cols


def test_v3_database_upgrades_in_place_without_rewriting(tmp_path):
    db_file = tmp_path / "v3.sqlite3"
    conn = schema.connect(str(db_file))
    try:
        assert schema.apply_migrations(conn, target=3) == 3
        conn.execute(
            "INSERT INTO affinity_ledger "
            "(persona_id, user_id, event_id, delta, reason, day, created_at) "
            "VALUES ('p', 'u', 'legacy', 0.03, 'legacy', '2026-09-20', "
            "'2026-09-20T10:00:00+00:00')"
        )
        conn.commit()

        assert schema.apply_migrations(conn) == 4
        row = conn.execute("SELECT * FROM affinity_ledger WHERE event_id = 'legacy'").fetchone()
        assert row["delta"] == pytest.approx(0.03)
        assert row["event_type"] == ""
        assert schema.get_schema_version(conn) == 4

        # the guard makes the ALTER re-runnable without error
        schema._migrate_v4(conn)
        assert schema.apply_migrations(conn) == 4
    finally:
        conn.close()


def test_v4_migration_is_idempotent(store):
    for _ in range(3):
        assert store.migrate() == 4
    assert set(schema.EXPECTED_TABLES).issubset(store.table_names())


def test_emotion_events_store_no_message_body(store):
    cols = {row[1] for row in store.connection.execute("PRAGMA table_info(emotion_events)")}
    assert not (cols & {"content", "text", "message", "raw", "body", "msg"})


async def test_life_state_energy_feeds_expression(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1", user_id="67890", affinity=0.0, updated_at=NOW.isoformat()
        )
    )
    store.upsert_life_state(
        LifeState(
            persona_id="p1",
            activity="relaxing",
            energy=0.8,
            scene="home",
            summary="",
            as_of=NOW.isoformat(),
        )
    )
    contract = ContractV1(store, clock=_clock())
    for i in range(10):  # valence 0.20
        await contract.record_emotion_event(
            UMO, event_type=EVENT_SUDDEN_WARMTH, dedupe_key=f"warm:{i}"
        )
    decision = await contract.expression_decision(UMO, persona_id="p1")
    assert decision["mode"] == "活泼"
