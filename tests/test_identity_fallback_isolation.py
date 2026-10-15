"""Companion identity fallback isolation (regressions).

Explicit canonical Person bindings remain shared; unresolved private and group
identities are isolated per complete platform instance / message type / session.
Legacy bare rows are retained and never exposed implicitly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.emotion import EVENT_GRATITUDE
from core.group import member_key_for
from core.memory_bridge import MemoryBridge
from core.relationship import parse_umo, private_fallback_key

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
NATIVE = "42"
UMO_A = f"aiocqhttp:FriendMessage:{NATIVE}"
UMO_B = f"telegram:FriendMessage:{NATIVE}"
GROUP_A = "aiocqhttp:GroupMessage:1000"
GROUP_B = "telegram:GroupMessage:1000"
PERSON = "person-zhang"


class _Star:
    def __init__(self, mapping=None, *, delay=0.0):
        self.mapping = dict(mapping or {})
        self.delay = delay

    async def resolve_person(self, umo):
        if self.delay:
            await asyncio.sleep(self.delay)
        person = self.mapping.get(umo)
        return {"person_id": person, "is_group": False} if person else {}


class _Metadata:
    def __init__(self, star):
        self.star_cls = star
        self.activated = True


class _Context:
    def __init__(self, star=None):
        self.metadata = _Metadata(star) if star is not None else None

    def get_registered_star(self, name):
        return self.metadata


def _bridge(mapping=None, **kwargs):
    from core.memory_bridge import MemoryBridge

    return MemoryBridge(_Context(_Star(mapping, **kwargs)), config={})


def _expected_scope(umo):
    return private_fallback_key(parse_umo(umo))


def test_fallback_key_is_collision_free_and_thread_safe():
    a = private_fallback_key(parse_umo("aiocqhttp:FriendMessage:42"))
    b = private_fallback_key(parse_umo("telegram:FriendMessage:42"))
    thread = private_fallback_key(parse_umo("aiocqhttp:FriendMessage:42:thread-1"))
    same_thread = private_fallback_key(parse_umo("aiocqhttp:FriendMessage:42:thread-1"))
    assert a != b
    assert a.startswith("p:aiocqhttp:FriendMessage:42")
    assert thread == same_thread
    assert thread.endswith(":thread-1")


def test_malformed_identity_fails_closed():
    assert private_fallback_key(parse_umo("")) == ""
    assert private_fallback_key(parse_umo("only-platform")) == ""
    assert private_fallback_key(parse_umo("platform:FriendMessage")) == ""
    assert private_fallback_key(parse_umo("aiocqhttp:GroupMessage:1000")) == ""


async def test_unresolved_private_state_is_platform_instance_isolated(store):
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge())
    first = await contract.record_emotion_event(UMO_A, event_type=EVENT_GRATITUDE, dedupe_key="e1")
    second = await contract.record_emotion_event(UMO_B, event_type=EVENT_GRATITUDE, dedupe_key="e1")

    assert first["applied"] and second["applied"]
    assert store.list_emotion_events(DEFAULT_PERSONA_ID, "42") == []
    assert len(store.list_emotion_events(DEFAULT_PERSONA_ID, _expected_scope(UMO_A))) == 1
    assert len(store.list_emotion_events(DEFAULT_PERSONA_ID, _expected_scope(UMO_B))) == 1


async def test_timeout_and_missing_bridge_use_isolated_fallback(store):
    slow = ContractV1(
        store,
        clock=lambda: NOW,
        memory_bridge=MemoryBridge(
            _Context(_Star({UMO_A: PERSON}, delay=0.05)),
            config={"memory_bridge": {"timeout_sec": 0.01}},
        ),
    )
    timeout_scope, _ = await slow._private_scope(parse_umo(UMO_A), UMO_A)
    assert timeout_scope == _expected_scope(UMO_A)


async def test_offline_map_invalid_stays_isolated(store, tmp_path):
    bad_map = tmp_path / "identity_map.json"
    bad_map.write_text("{not-json", encoding="utf-8")
    from core.identity_map import IdentityMap
    from core.memory_bridge import MemoryBridge

    bridge = MemoryBridge(_Context(), config={}, identity_map=IdentityMap(path=bad_map))
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=bridge)
    scope, person_id = await contract._private_scope(parse_umo(UMO_A), UMO_A)
    assert scope == _expected_scope(UMO_A)
    assert person_id == ""


async def test_explicit_canonical_person_remains_shared(store):
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_bridge({UMO_A: PERSON, UMO_B: PERSON})
    )
    await contract.record_emotion_event(UMO_A, event_type=EVENT_GRATITUDE, dedupe_key="e1")
    rel_a = await contract.get_relationship(UMO_A)
    rel_b = await contract.get_relationship(UMO_B)
    assert rel_a["affinity"] > 0
    assert rel_b["affinity"] == rel_a["affinity"]


async def test_bare_legacy_data_is_not_automatically_exposed(store):
    # A pre-isolation row keyed only by the native sender id.
    store.record_user_message(DEFAULT_PERSONA_ID, NATIVE, now=NOW, count=3)
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge())
    ctx = await contract.get_proactive_context(UMO_A)
    assert ctx["unanswered_streak"] == 0
    assert store.get_interaction_dynamics(DEFAULT_PERSONA_ID, NATIVE).message_count == 3
    assert (
        store.get_interaction_dynamics(
            DEFAULT_PERSONA_ID, private_fallback_key(parse_umo(UMO_A))
        ).message_count
        == 0
    )


async def test_group_same_native_id_is_platform_isolated(store):
    contract = ContractV1(store, config={}, clock=lambda: NOW)
    await contract.record_group_activity(GROUP_A, member_id="42", now=NOW)
    await contract.record_group_activity(GROUP_B, member_id="42", now=NOW)

    assert store.get_group_activity(GROUP_A)["message_count"] == 1
    assert store.get_group_activity(GROUP_B)["message_count"] == 1
    assert (
        store.get_group_member(GROUP_A, member_key_for(parse_umo(GROUP_A).user_id, "42"))[
            "msg_count"
        ]
        == 1
    )
    assert store.get_group_activity("group:1000") is None


async def test_malformed_group_identity_fails_closed(store):
    contract = ContractV1(store, clock=lambda: NOW)
    result = await contract.record_group_activity("aiocqhttp:GroupMessage")
    assert result["applied"] is False
    assert result["degraded"] is True


async def test_contract_v1_capability_shape_unchanged(store):
    info = await ContractV1(store).get_contract_info()
    assert info["api_version"] == 1
    assert info["capabilities"]["identity_binding"] is True
    assert info["capabilities"]["identity_map"] is True


async def test_group_context_uses_complete_umo_not_native_group_key(store):
    contract = ContractV1(store, clock=lambda: NOW)
    await contract.record_group_activity(GROUP_A, member_id="42", now=NOW)
    context = await contract.get_group_context(GROUP_B, member_id="42")

    assert context["group"]["member_count"] == 0
    assert context["member"]["is_known"] is False
    assert store.count_group_members(GROUP_A) == 1
