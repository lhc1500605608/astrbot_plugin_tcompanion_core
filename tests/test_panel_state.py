"""Phase 3-C1b (v1.6): read-only panel projections ``group-state``/``growth-state``.

The two routes reuse the frozen contract but must stay pure reads: the group
projection never stamps a participation slot, and neither projection leaks
private/group data across the boundary.
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.emotion import EVENT_GRATITUDE
from core.relationship import STAGE_INTIMATE, RelationshipState
from core.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = "astrbot_plugin_tcompanion_core"

GROUP_UMO = "aiocqhttp:GroupMessage:10001"
PRIVATE_UMO = "webchat:FriendMessage:webchat!u1!private"
SCOPE = "webchat!u1!private"
BASE = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

GROUP_KEYS = {
    "umo",
    "member_count",
    "activity_level",
    "topic",
    "topic_age_min",
    "last_activity",
    "allow",
    "reason",
    "cooldown_remaining_sec",
    "hourly_remaining",
}
GROWTH_KEYS = {"persona_id", "user_id", "level", "progress", "max_level", "traits"}


def _contract(config=None, now=BASE):
    store = Store.open(":memory:")
    contract = ContractV1(store, config=config or {}, clock=lambda: now)
    return store, contract


def _seed_relationship(store, affinity=0.9, stage=STAGE_INTIMATE):
    store.save_relationship_state(
        RelationshipState(
            persona_id=DEFAULT_PERSONA_ID,
            user_id=SCOPE,
            affinity=affinity,
            stage=stage,
            updated_at=BASE.isoformat(),
        )
    )


async def test_list_group_states_flat_shape():
    _, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, member_id="42", topic="周末计划")
    items = contract.list_group_states()
    assert len(items) == 1
    item = items[0]
    assert set(item) == GROUP_KEYS
    assert item["umo"] == GROUP_UMO
    assert item["member_count"] == 1
    assert item["topic"] == "周末计划"
    assert item["allow"] is True
    assert item["reason"] == "ok"
    assert item["topic_age_min"] == 0.0
    # No private/person/relationship fields leak into the group view.
    assert not ({"persona_id", "user_id", "person", "relationship"} & set(item))


async def test_list_group_states_is_pure_read():
    store, contract = _contract()
    await contract.record_group_activity(GROUP_UMO, member_id="42", topic="hi")
    before = store.get_group_activity(GROUP_UMO)
    assert contract.list_group_states()[0]["allow"] is True
    after = store.get_group_activity(GROUP_UMO)
    assert after["part_hour_count"] == before["part_hour_count"]
    assert after["last_participation_ts"] == before["last_participation_ts"] == ""


async def test_list_group_states_empty_when_disabled():
    _, contract = _contract(config={"group": {"enabled": False}})
    await contract.record_group_activity(GROUP_UMO, member_id="42")
    assert contract.list_group_states() == []


async def test_list_group_states_empty_without_rows():
    _, contract = _contract()
    assert contract.list_group_states() == []


async def test_list_growth_states_flat_shape():
    store, contract = _contract()
    _seed_relationship(store)
    items = contract.list_growth_states()
    assert len(items) == 1
    item = items[0]
    assert set(item) == GROWTH_KEYS
    assert item["persona_id"] == DEFAULT_PERSONA_ID
    assert item["user_id"] == SCOPE
    assert item["max_level"] == 10
    assert item["level"] > 0
    # The read path idempotently persists the high-water mark.
    assert store.get_growth_state(DEFAULT_PERSONA_ID, SCOPE)["level"] >= item["level"]


async def test_list_growth_states_empty_when_disabled_or_reset():
    for config in ({"growth": {"enabled": False}}, {"growth": {"reset": True}}):
        store, contract = _contract(config=config)
        _seed_relationship(store)
        assert contract.list_growth_states() == []


async def test_list_growth_states_has_no_group_rows():
    store, contract = _contract()
    _seed_relationship(store)
    await contract.record_group_activity(GROUP_UMO, member_id="42")
    items = contract.list_growth_states()
    assert [item["user_id"] for item in items] == [SCOPE]


# -- route handlers --------------------------------------------------------


def _stub_astrbot() -> dict[str, types.ModuleType]:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star_mod = types.ModuleType("astrbot.api.star")
    web = types.ModuleType("astrbot.api.web")

    class AstrMessageEvent:
        pass

    class _Filter:
        def command(self, *_args, **_kwargs):
            def deco(fn):
                return fn

            return deco

    class Context:
        def __init__(self):
            self.web_apis: list = []

        def register_web_api(self, *args, **kwargs):
            self.web_apis.append((args, kwargs))

    class Star:
        def __init__(self, context):
            self.context = context

    def register(*_args, **_kwargs):
        def deco(cls):
            return cls

        return deco

    def json_response(payload, status_code=200):
        return {"payload": payload, "status_code": status_code}

    import logging

    api.logger = logging.getLogger("astrbot")
    event.AstrMessageEvent = AstrMessageEvent
    event.filter = _Filter()
    star_mod.Context = Context
    star_mod.Star = Star
    star_mod.register = register
    web.json_response = json_response
    return {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star_mod,
        "astrbot.api.web": web,
    }


@pytest.fixture()
def star_cls(monkeypatch):
    for name, mod in _stub_astrbot().items():
        monkeypatch.setitem(sys.modules, name, mod)
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(REPO_ROOT)]
    monkeypatch.setitem(sys.modules, PKG, pkg)
    sys.modules.pop(f"{PKG}.main", None)
    return importlib.import_module(f"{PKG}.main").TCompanionCore


def _make_star(star_cls, store):
    from astrbot.api.star import Context

    star = star_cls(Context())
    star._store = store
    star.contract = ContractV1(store, clock=lambda: BASE)
    return star


async def test_routes_registered(star_cls):
    from astrbot.api.star import Context

    star = star_cls(Context())
    paths = {args[0] for args, _ in star.context.web_apis}
    assert f"/{PKG}/group-state" in paths
    assert f"/{PKG}/growth-state" in paths


async def test_api_group_state_returns_flat_items(star_cls):
    store = Store.open(":memory:")
    star = _make_star(star_cls, store)
    await star.record_group_activity(GROUP_UMO, member_id="42", topic="hi")
    response = await star.api_group_state()
    assert response["status_code"] == 200
    assert set(response["payload"]["items"][0]) == GROUP_KEYS
    store.close()


async def test_api_growth_state_returns_flat_items(star_cls):
    store = Store.open(":memory:")
    _seed_relationship(store)
    star = _make_star(star_cls, store)
    response = await star.api_growth_state()
    assert response["status_code"] == 200
    assert set(response["payload"]["items"][0]) == GROWTH_KEYS
    store.close()


async def test_api_state_routes_503_without_store(star_cls):
    store, _ = _contract()
    star = _make_star(star_cls, store)
    star._store = None
    for handler in (star.api_group_state, star.api_growth_state):
        response = await handler()
        assert response["status_code"] == 503
        assert response["payload"] == {"error": "store not ready"}
    store.close()


async def test_growth_state_matches_growth_context():
    store, contract = _contract()
    _seed_relationship(store)
    await contract.record_emotion_event(PRIVATE_UMO, event_type=EVENT_GRATITUDE)
    ctx = await contract.get_growth_context(PRIVATE_UMO)
    item = contract.list_growth_states()[0]
    assert item["level"] == ctx["growth"]["level"]
    assert item["progress"] == ctx["growth"]["progress"]
    assert item["traits"] == ctx["growth"]["traits"]
