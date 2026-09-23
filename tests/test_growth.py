"""Phase 3-C (v1.6): lightweight, bounded, rollback-able growth."""

from __future__ import annotations

from datetime import datetime, timezone

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.emotion import EVENT_GRATITUDE, EXPRESSION_MODES, expression_for
from core.growth import GROWTH_DRIFT_HARD_CAP, with_growth_drift
from core.relationship import STAGE_INTIMATE, RelationshipState
from core.store import Store

PRIVATE_UMO = "webchat:FriendMessage:webchat!u1!private"
GROUP_UMO = "aiocqhttp:GroupMessage:10001"
SCOPE = "webchat!u1!private"
BASE = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _contract(config=None, now=BASE):
    store = Store.open(":memory:")
    contract = ContractV1(store, config=config or {}, clock=lambda: now)
    return store, contract


def _seed_relationship(store, affinity=0.9, stage=STAGE_INTIMATE):
    store.save_relationship_state(
        RelationshipState(
            persona_id="p1",
            user_id=SCOPE,
            affinity=affinity,
            stage=stage,
            updated_at=BASE.isoformat(),
        )
    )


async def test_capabilities_expose_group_and_growth():
    _, contract = _contract()
    info = await contract.get_contract_info()
    assert info["capabilities"]["group_aware"] is True
    assert info["capabilities"]["growth"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


async def test_growth_group_is_isolated():
    _, contract = _contract()
    ctx = await contract.get_growth_context(GROUP_UMO)
    assert ctx["is_group"] is True
    assert ctx["isolated"] is True
    assert ctx["growth"] is None
    assert ctx["drift"] == {"warmth_delta": 0.0, "verbosity_delta": 0.0}


async def test_growth_fresh_scope_is_level_zero():
    _, contract = _contract()
    ctx = await contract.get_growth_context(PRIVATE_UMO)
    assert ctx["is_group"] is False and ctx["isolated"] is False
    assert ctx["growth"]["level"] == 0
    assert ctx["growth"]["progress"] == 0.0
    assert ctx["growth"]["traits"] == []
    assert ctx["drift"]["warmth_delta"] == 0.0


async def test_growth_disabled_returns_empty():
    _, contract = _contract(config={"growth": {"enabled": False}})
    ctx = await contract.get_growth_context(PRIVATE_UMO)
    assert ctx["growth"] is None
    assert ctx["drift"] == {"warmth_delta": 0.0, "verbosity_delta": 0.0}


async def test_growth_reset_clears_storage():
    store, contract = _contract(config={"growth": {"reset": True}})
    store.upsert_growth_state(DEFAULT_PERSONA_ID, SCOPE, level=5, xp=5.0, now=BASE)
    assert store.get_growth_state(DEFAULT_PERSONA_ID, SCOPE)["level"] == 5

    ctx = await contract.get_growth_context(PRIVATE_UMO)
    assert ctx["growth"] is None
    cleared = store.get_growth_state(DEFAULT_PERSONA_ID, SCOPE)
    assert cleared["level"] == 0
    assert cleared["reset_at"] != ""


async def test_growth_derives_level_traits_and_progress():
    store, contract = _contract()
    _seed_relationship(store, affinity=0.9, stage=STAGE_INTIMATE)
    await contract.record_emotion_event(
        PRIVATE_UMO, event_type=EVENT_GRATITUDE, dedupe_key="msg:1", now=BASE
    )

    ctx = await contract.get_growth_context(PRIVATE_UMO)
    growth = ctx["growth"]
    assert growth["max_level"] == 10
    assert 0 < growth["level"] <= growth["max_level"]
    assert 0.0 <= growth["progress"] <= 1.0
    assert "亲近" in growth["traits"]
    assert 0.0 < ctx["drift"]["warmth_delta"] <= GROWTH_DRIFT_HARD_CAP
    assert ctx["drift"]["verbosity_delta"] == round(
        ctx["drift"]["warmth_delta"] * 0.5, 4
    )


async def test_growth_level_bounded_by_max_level():
    store, contract = _contract(config={"growth": {"max_level": 1}})
    _seed_relationship(store, affinity=0.95, stage=STAGE_INTIMATE)
    ctx = await contract.get_growth_context(PRIVATE_UMO)
    assert ctx["growth"]["level"] <= 1
    assert ctx["growth"]["max_level"] == 1
    assert ctx["drift"]["warmth_delta"] <= GROWTH_DRIFT_HARD_CAP


def test_with_growth_drift_is_bounded_and_keeps_mode():
    decision = expression_for(stage=STAGE_INTIMATE)
    base_mode = decision["mode"]
    base_warmth = decision["style_hints"]["warmth"]

    drifted = with_growth_drift(decision, GROWTH_DRIFT_HARD_CAP)
    assert drifted["mode"] == base_mode
    assert drifted["style_hints"]["warmth"] == round(base_warmth + 0.05, 4)

    # non-positive drift is a no-op
    assert with_growth_drift(decision, 0.0) == decision
    assert with_growth_drift(decision, -0.2) == decision


async def test_expression_decision_growth_drift_never_changes_mode():
    store, contract = _contract()
    _seed_relationship(store, affinity=0.9, stage=STAGE_INTIMATE)

    enabled = await contract.expression_decision(PRIVATE_UMO)
    disabled_contract = ContractV1(
        store, config={"growth": {"enabled": False}}, clock=lambda: BASE
    )
    disabled = await disabled_contract.expression_decision(PRIVATE_UMO)

    assert enabled["mode"] == disabled["mode"]
    assert enabled["mode"] in EXPRESSION_MODES
    delta = round(enabled["style_hints"]["warmth"] - disabled["style_hints"]["warmth"], 4)
    assert 0.0 < delta <= GROWTH_DRIFT_HARD_CAP
