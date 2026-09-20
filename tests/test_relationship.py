"""T2 acceptance tests: stages, ledger rules, decay, dynamics, isolation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.contract import ContractV1
from core.relationship import (
    DAILY_POSITIVE_CAP,
    STAGE_ACQUAINTED,
    STAGE_CLOSE,
    STAGE_FAMILIAR,
    STAGE_INTIMATE,
    STAGE_STRANGER,
    RelationshipState,
    cap_event_delta,
    decayed,
    derive_bond,
    effective_delta,
    ignored_decay_factor,
    parse_umo,
    stage_for,
)


def _dt(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


# -- stage mapping --------------------------------------------------------
@pytest.mark.parametrize(
    ("affinity", "expected"),
    [
        (0.0, STAGE_STRANGER),
        (0.19, STAGE_STRANGER),
        (0.2, STAGE_ACQUAINTED),
        (0.39, STAGE_ACQUAINTED),
        (0.4, STAGE_FAMILIAR),
        (0.6, STAGE_CLOSE),
        (0.79, STAGE_CLOSE),
        (0.8, STAGE_INTIMATE),
        (1.0, STAGE_INTIMATE),
    ],
)
def test_stage_boundaries(affinity, expected):
    assert stage_for(affinity) == expected


def test_downgrade_hysteresis_holds_inside_band():
    # 0.39 is below 熟悉's floor (0.4) but within the 0.02 hysteresis band.
    assert stage_for(0.39, previous=STAGE_FAMILIAR) == STAGE_FAMILIAR
    # Falling past the band downgrades.
    assert stage_for(0.37, previous=STAGE_FAMILIAR) == STAGE_ACQUAINTED
    # Upgrades are immediate.
    assert stage_for(0.41, previous=STAGE_STRANGER) == STAGE_FAMILIAR


def test_affinity_clamped():
    assert stage_for(-1.0) == STAGE_STRANGER
    assert stage_for(5.0) == STAGE_INTIMATE


# -- ledger policy (pure) -------------------------------------------------
def test_single_event_cap():
    assert cap_event_delta(0.5) == pytest.approx(0.03)
    assert cap_event_delta(0.01) == pytest.approx(0.01)
    assert cap_event_delta(-0.5) == 0.0


def test_daily_allowance_uses_remaining_budget():
    assert effective_delta(0.03, 0.0) == pytest.approx(0.03)
    assert effective_delta(0.03, 0.09) == pytest.approx(0.01)
    assert effective_delta(0.03, DAILY_POSITIVE_CAP) == 0.0


def test_decay_converges_toward_zero():
    assert decayed(0.5, 1) == pytest.approx(0.495)
    assert decayed(0.012, 3) == 0.0
    assert decayed(0.5, 0) == pytest.approx(0.5)


def test_ignored_decay_factor():
    assert ignored_decay_factor(0) == pytest.approx(1.0)
    assert ignored_decay_factor(1) == pytest.approx(0.5)
    assert ignored_decay_factor(3) == pytest.approx(0.25)


def test_derive_bond_requires_stage_and_event():
    assert derive_bond(STAGE_CLOSE, has_bond_event=True) is True
    assert derive_bond(STAGE_CLOSE, has_bond_event=False) is False
    assert derive_bond(STAGE_FAMILIAR, has_bond_event=True) is False
    # Bond revokes when the stage falls back below 亲近.
    assert derive_bond(STAGE_FAMILIAR, has_bond_event=False, previous=True) is False


# -- umo parsing / isolation ---------------------------------------------
def test_parse_umo_private_and_group():
    private = parse_umo("aiocqhttp:FriendMessage:67890")
    assert private.is_group is False
    assert private.user_id == "67890"

    group = parse_umo("aiocqhttp:GroupMessage:12345")
    assert group.is_group is True
    assert group.isolated is True
    assert group.user_id == "group:12345"
    assert group.user_id != private.user_id


# -- store: caps / dedup / decay -----------------------------------------
def test_store_single_event_cap(store):
    result = store.apply_affinity_event("p1", "u1", "e1", 0.5, now=_dt(1))
    assert result["applied"] is True
    assert result["delta"] == pytest.approx(0.03)
    assert result["state"].affinity == pytest.approx(0.03)


def test_store_daily_positive_cap(store):
    for i in range(3):
        store.apply_affinity_event("p1", "u1", f"e{i}", 0.03, now=_dt(1))
    fourth = store.apply_affinity_event("p1", "u1", "e3", 0.03, now=_dt(1))
    assert fourth["delta"] == pytest.approx(0.01)  # only 0.01 budget left

    state = store.get_relationship_state("p1", "u1")
    assert state.affinity == pytest.approx(DAILY_POSITIVE_CAP)

    # The next event the same day is fully blocked by the daily cap.
    fifth = store.apply_affinity_event("p1", "u1", "e4", 0.03, now=_dt(1))
    assert fifth["applied"] is False
    assert fifth["delta"] == 0.0

    # A new day resets the allowance.
    next_day = store.apply_affinity_event("p1", "u1", "e5", 0.03, now=_dt(2))
    assert next_day["applied"] is True


def test_store_event_dedup_is_idempotent(store):
    first = store.apply_affinity_event("p1", "u1", "same-event", 0.03, now=_dt(1))
    second = store.apply_affinity_event("p1", "u1", "same-event", 0.03, now=_dt(1))
    assert first["applied"] is True
    assert second["duplicate"] is True
    assert second["applied"] is False

    state = store.get_relationship_state("p1", "u1")
    assert state.affinity == pytest.approx(0.03)
    assert len(store.list_affinity_ledger("p1", "u1")) == 1


def test_store_negative_event_does_not_deduct(store):
    store.apply_affinity_event("p1", "u1", "e1", 0.03, now=_dt(1))
    result = store.apply_affinity_event("p1", "u1", "e2", -0.5, now=_dt(1))
    assert result["applied"] is False
    assert store.get_relationship_state("p1", "u1").affinity == pytest.approx(0.03)


def test_store_decay_per_day_and_idempotent(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="u1",
            affinity=0.5,
            stage=STAGE_FAMILIAR,
            last_active_day="2026-09-01",
            updated_at=_dt(1).isoformat(),
        )
    )
    decayed_state = store.apply_decay("p1", "u1", now=_dt(3))
    assert decayed_state.affinity == pytest.approx(0.49)  # 2 idle days

    # Same-day re-run must not decay twice.
    assert store.apply_decay("p1", "u1", now=_dt(3)).affinity == pytest.approx(0.49)


def test_store_decay_converges_to_zero(store):
    store.apply_affinity_event("p1", "u1", "e1", 0.03, now=_dt(1))
    state = store.apply_decay("p1", "u1", now=_dt(11))
    assert state.affinity == 0.0
    assert state.stage == STAGE_STRANGER


def test_store_never_monotonic_inflation(store):
    # 4 max events/day over 20 days would be +2.0 without caps.
    for day in range(1, 21):
        for i in range(4):
            store.apply_affinity_event("p1", "u1", f"d{day}-{i}", 0.03, now=_dt(day))
    state = store.get_relationship_state("p1", "u1")
    assert state.affinity <= 1.0

    # An idle stretch pulls it back down — never a one-way ratchet.
    decayed_state = store.apply_decay("p1", "u1", now=_dt(30))
    assert decayed_state.affinity < state.affinity


def test_store_stage_transition_persisted(store):
    moment = _dt(1)
    state = None
    for i in range(4):
        state = store.apply_affinity_event("p1", "u1", f"e{i}", 0.03, now=moment)["state"]
    assert state.affinity == pytest.approx(0.10)  # daily cap
    assert state.stage == STAGE_STRANGER

    state = store.apply_affinity_event("p1", "u1", "e9", 0.03, now=_dt(2))["state"]
    assert state.affinity == pytest.approx(0.13)
    assert state.stage == STAGE_STRANGER


# -- interaction dynamics -------------------------------------------------
def test_unanswered_streak_and_ignored_factor(store):
    for i in range(3):
        dynamics = store.record_proactive_outcome("p1", "u1", sent=True, now=_dt(1, 10, i))
    assert dynamics.unanswered_streak == 3
    assert dynamics.proactive_sent == 3
    assert dynamics.ignored_decay_factor == pytest.approx(0.25)


def test_user_reply_resets_streak_and_records_delay(store):
    store.record_proactive_outcome("p1", "u1", sent=True, now=_dt(1, 10, 0))
    dynamics = store.record_user_message("p1", "u1", now=_dt(1, 10, 2))
    assert dynamics.unanswered_streak == 0
    assert dynamics.message_count == 1
    assert dynamics.avg_reply_delay == pytest.approx(120.0)


def test_replied_outcome_resets_streak(store):
    store.record_proactive_outcome("p1", "u1", sent=True, now=_dt(1, 10, 0))
    dynamics = store.record_proactive_outcome(
        "p1", "u1", sent=True, replied=True, now=_dt(1, 11, 0)
    )
    assert dynamics.unanswered_streak == 0
    assert dynamics.proactive_replied == 1


def test_unsent_outcome_is_noop(store):
    dynamics = store.record_proactive_outcome("p1", "u1", sent=False, now=_dt(1))
    assert dynamics.proactive_sent == 0
    assert dynamics.unanswered_streak == 0


# -- contract projection --------------------------------------------------
async def test_contract_relationship_reads_real_state(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.42,
            stage=STAGE_FAMILIAR,
            updated_at=_dt(1).isoformat(),
        )
    )
    rel = await ContractV1(store).get_relationship("aiocqhttp:FriendMessage:67890", "p1")
    assert rel["stage"] == STAGE_FAMILIAR
    assert rel["affinity"] == pytest.approx(0.42)
    assert rel["degraded"] is False


async def test_contract_group_does_not_inherit_private_relationship(store):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id="67890",
            affinity=0.7,
            stage=STAGE_CLOSE,
            updated_at=_dt(1).isoformat(),
        )
    )
    contract = ContractV1(store)

    private = await contract.get_relationship("aiocqhttp:FriendMessage:67890", "p1")
    assert private["degraded"] is False
    assert private["affinity"] == pytest.approx(0.7)

    group = await contract.get_relationship("aiocqhttp:GroupMessage:67890", "p1")
    assert group["degraded"] is True
    assert group["affinity"] == 0.0
    assert group["stage"] == STAGE_STRANGER


async def test_contract_empty_umo_is_degraded(store):
    rel = await ContractV1(store).get_relationship("")
    assert rel["degraded"] is True
    assert rel["stage"] == STAGE_STRANGER
