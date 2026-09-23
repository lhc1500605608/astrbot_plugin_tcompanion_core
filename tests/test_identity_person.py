"""v1.5: Person identity bridge, person-keyed private state, one-time migration.

Covers the three deliverables of TMEAAA-542:

* ``MemoryBridge.resolve_person`` — read-only, TTL-cached, fail-closed;
* private relationship/emotion/life-line keyed by ``person_id`` (shared across
  adapters), groups still isolated by ``group:<session>``;
* ``Store.migrate_person_keys`` / ``rollback_person_migration`` — idempotent,
  JSON-backed, group rows untouched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.emotion import EVENT_GRATITUDE, EVENT_MISUNDERSTOOD
from core.memory_bridge import MemoryBridge
from core.relationship import STAGE_FAMILIAR, STAGE_STRANGER, RelationshipState

UMO_A = "aiocqhttp:FriendMessage:42"
UMO_B = "telegram:FriendMessage:7"
GROUP_UMO = "aiocqhttp:GroupMessage:1000"
PERSON = "person-zhang"
NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)


class _IdentityStar:
    """Fake memory plugin exposing the public ``resolve_person`` API."""

    def __init__(self, mapping=None, *, delay=0.0, raises=None):
        self._mapping = dict(mapping or {})
        self._delay = delay
        self._raises = raises
        self.calls = 0

    async def resolve_person(self, umo):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        parts = str(umo or "").split(":")
        if len(parts) >= 2 and "group" in parts[1].lower():
            return {
                "person_id": "",
                "adapter": parts[0],
                "adapter_user_id": parts[-1],
                "is_group": True,
            }
        person_id = self._mapping.get(umo, "")
        if not person_id:
            return {}
        return {
            "person_id": person_id,
            "adapter": parts[0],
            "adapter_user_id": parts[-1],
            "is_group": False,
        }


class _LegacyStar:
    """An older memory plugin without ``resolve_person``."""


class _Metadata:
    def __init__(self, star, activated=True):
        self.star_cls = star
        self.activated = activated


class _Context:
    def __init__(self, metadata=None):
        self._metadata = metadata

    def get_registered_star(self, name):
        return self._metadata


def _bridge(star=None, *, config=None, activated=True, clock=None):
    context = _Context(_Metadata(star, activated) if star is not None else None)
    return MemoryBridge(context, config=config, clock=clock)


def _identity_star(mapping=None, *, config=None, **star_kwargs):
    return _bridge(_IdentityStar(mapping, **star_kwargs), config=config)


# -- bridge.resolve_person -------------------------------------------------
async def test_resolve_person_private_returns_person_id():
    bridge = _identity_star({UMO_A: PERSON})
    assert await bridge.resolve_person(UMO_A) == PERSON


async def test_resolve_person_group_returns_none():
    bridge = _identity_star({GROUP_UMO: PERSON})
    assert await bridge.resolve_person(GROUP_UMO) is None


async def test_resolve_person_empty_umo_returns_none():
    bridge = _identity_star({UMO_A: PERSON})
    assert await bridge.resolve_person("") is None
    assert await bridge.resolve_person("   ") is None


async def test_resolve_person_missing_plugin_returns_none():
    bridge = _bridge(None)
    assert await bridge.resolve_person(UMO_A) is None
    assert bridge.stats()["degrade"] >= 1


async def test_resolve_person_inactive_plugin_returns_none():
    bridge = _bridge(_IdentityStar({UMO_A: PERSON}), activated=False)
    assert await bridge.resolve_person(UMO_A) is None


async def test_resolve_person_older_plugin_without_method_returns_none():
    bridge = _bridge(_LegacyStar())
    assert await bridge.resolve_person(UMO_A) is None


async def test_resolve_person_empty_result_returns_none():
    bridge = _identity_star({})
    assert await bridge.resolve_person(UMO_A) is None


async def test_resolve_person_timeout_returns_none():
    bridge = _identity_star(
        {UMO_A: PERSON}, delay=0.05, config={"memory_bridge": {"timeout_sec": 0.01}}
    )
    assert await bridge.resolve_person(UMO_A) is None
    assert bridge.stats()["timeout"] >= 1


async def test_resolve_person_exception_returns_none():
    bridge = _identity_star(raises=RuntimeError("boom"))
    assert await bridge.resolve_person(UMO_A) is None


async def test_resolve_person_disabled_config_does_not_resolve():
    star = _IdentityStar({UMO_A: PERSON})
    bridge = _bridge(star, config={"memory_bridge": {"enabled": False}})
    assert await bridge.resolve_person(UMO_A) is None
    assert star.calls == 0


async def test_resolve_person_cache_avoids_repeat_calls():
    star = _IdentityStar({UMO_A: PERSON})
    now = [1000.0]
    bridge = _bridge(star, clock=lambda: now[0])
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert star.calls == 1

    now[0] += 6 * 60  # past the default 5-minute TTL
    await bridge.resolve_person(UMO_A)
    assert star.calls == 2


async def test_resolve_person_caches_negative_result():
    star = _IdentityStar({})
    bridge = _bridge(star)
    assert await bridge.resolve_person(UMO_A) is None
    assert await bridge.resolve_person(UMO_A) is None
    assert star.calls == 1


# -- person-keyed private state -------------------------------------------
async def test_private_state_shared_across_adapters(store):
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_identity_star({UMO_A: PERSON, UMO_B: PERSON})
    )
    recorded = await contract.record_emotion_event(
        UMO_A, event_type=EVENT_GRATITUDE, dedupe_key="msg:1"
    )
    assert recorded["applied"] is True

    # The other adapter reads the same ledger/relationship (same Person).
    emotion = await contract.get_emotion_context(UMO_B)
    assert emotion["degraded"] is False
    assert emotion["valence"] > 0
    rel = await contract.get_relationship(UMO_B)
    assert rel["affinity"] > 0

    # ...and the write landed under the person key, not the adapter session id.
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, "42") is None


async def test_proactive_context_echoes_person_id(store):
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_identity_star({UMO_B: PERSON})
    )
    ctx = await contract.get_proactive_context(UMO_B)
    assert ctx["person_id"] == PERSON


async def test_life_line_shared_across_adapters(store):
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_identity_star({UMO_A: PERSON, UMO_B: PERSON})
    )
    store.insert_diary(
        DEFAULT_PERSONA_ID, PERSON, "2026-09-20", summary="共同回忆", mood="平静"
    )
    first = await contract.get_diary(UMO_A, day="2026-09-20")
    second = await contract.get_diary(UMO_B, day="2026-09-20")
    assert first == second
    assert first["summary"] == "共同回忆"
    assert store.get_diary(DEFAULT_PERSONA_ID, "42", "2026-09-20") is None


async def test_group_scope_isolated_from_person(store):
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_identity_star({UMO_A: PERSON, GROUP_UMO: PERSON})
    )
    await contract.record_emotion_event(UMO_A, event_type=EVENT_GRATITUDE, dedupe_key="msg:1")
    group_ctx = await contract.get_proactive_context(GROUP_UMO)
    assert "person_id" not in group_ctx
    assert group_ctx["emotion_state"] is None
    group_rel = await contract.get_relationship(GROUP_UMO)
    assert group_rel["stage"] == STAGE_STRANGER
    assert group_rel["degraded"] is True


async def test_proactive_context_omits_person_id_without_bridge(store):
    contract = ContractV1(store, clock=lambda: NOW)
    ctx = await contract.get_proactive_context(UMO_A)
    assert "person_id" not in ctx


async def test_fail_closed_falls_back_to_parse_umo(store):
    # Bridge present but cannot resolve a Person -> parse_umo().user_id key.
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_identity_star({}))
    await contract.record_emotion_event(
        UMO_A, event_type=EVENT_MISUNDERSTOOD, dedupe_key="msg:neg"
    )
    assert store.resolve_relationship_state("42") is None  # negative floor, no row
    assert store.list_emotion_events(DEFAULT_PERSONA_ID, "42", limit=10)
    assert not store.list_emotion_events(DEFAULT_PERSONA_ID, "aiocqhttp:42", limit=10)


async def test_unavailable_bridge_matches_plain_output(store):
    plain = ContractV1(store, clock=lambda: NOW)
    unavailable = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(None))
    assert await unavailable.get_proactive_context(UMO_A) == await plain.get_proactive_context(
        UMO_A
    )
    assert await unavailable.get_emotion_context(UMO_A) == await plain.get_emotion_context(UMO_A)
    assert await unavailable.get_life_line(UMO_A) == await plain.get_life_line(UMO_A)
    assert await unavailable.get_relationship(UMO_A) == await plain.get_relationship(UMO_A)


async def test_capabilities_expose_identity_binding(store):
    info = await ContractV1(store).get_contract_info()
    assert info["capabilities"]["identity_binding"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


# -- one-time migration ----------------------------------------------------
def _rel(user_id, affinity):
    return RelationshipState(
        persona_id=DEFAULT_PERSONA_ID,
        user_id=user_id,
        affinity=affinity,
        stage=STAGE_FAMILIAR,
        updated_at=NOW.isoformat(),
    )


def _seed_legacy_rows(store):
    store.save_relationship_state(_rel("aiocqhttp:42", 0.4))
    store.record_user_message(DEFAULT_PERSONA_ID, "aiocqhttp:42", now=NOW, count=3)
    store.apply_emotion_event(
        DEFAULT_PERSONA_ID,
        "aiocqhttp:42",
        event_id="m1",
        event_type=EVENT_GRATITUDE,
        delta=0.02,
        now=NOW,
    )
    store.insert_diary(DEFAULT_PERSONA_ID, "aiocqhttp:42", "2026-09-20", summary="x", mood="平静")
    store.upsert_sleep_window(
        DEFAULT_PERSONA_ID, "aiocqhttp:42", "2026-09-21", start_min=1380, end_min=450, source="inferred"
    )
    # A group row must never move.
    store.save_relationship_state(_rel("group:1000", 0.3))


def test_migrate_person_keys_merges_and_is_idempotent(store, tmp_path):
    _seed_legacy_rows(store)
    result = store.migrate_person_keys(
        PERSON, ["aiocqhttp:42"], backup_dir=tmp_path, now=NOW
    )
    assert result["ok"] is True
    assert result["noop"] is False
    assert result["backup_path"]

    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, "aiocqhttp:42") is None
    stats = store.get_interaction_dynamics(DEFAULT_PERSONA_ID, PERSON)
    assert stats.message_count == 3
    assert store.list_emotion_events(DEFAULT_PERSONA_ID, PERSON)
    assert store.get_diary(DEFAULT_PERSONA_ID, PERSON, "2026-09-20") is not None
    assert store.get_sleep_window(DEFAULT_PERSONA_ID, PERSON, "2026-09-21") is not None
    # group row untouched
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, "group:1000") is not None

    again = store.migrate_person_keys(PERSON, ["aiocqhttp:42"], backup_dir=tmp_path, now=NOW)
    assert again["noop"] is True


def test_migrate_conflict_aggregates(store, tmp_path):
    store.save_relationship_state(_rel("aiocqhttp:42", 0.4))
    store.save_relationship_state(_rel(PERSON, 0.25))
    store.record_user_message(DEFAULT_PERSONA_ID, "aiocqhttp:42", now=NOW, count=2)
    store.record_user_message(DEFAULT_PERSONA_ID, PERSON, now=NOW, count=5)

    store.migrate_person_keys(PERSON, ["aiocqhttp:42"], backup_dir=tmp_path, now=NOW)

    rel = store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON)
    assert rel.affinity == pytest.approx(0.4)
    assert store.get_interaction_dynamics(DEFAULT_PERSONA_ID, PERSON).message_count == 7
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, "aiocqhttp:42") is None


def test_migrate_invalid_args_is_noop(store, tmp_path):
    assert store.migrate_person_keys("", ["a"], backup_dir=tmp_path)["ok"] is False
    assert store.migrate_person_keys(PERSON, [], backup_dir=tmp_path)["ok"] is False
    # Group aliases are ignored entirely.
    result = store.migrate_person_keys(
        PERSON, ["group:1000"], backup_dir=tmp_path, now=NOW
    )
    assert result["ok"] is False


def test_rollback_restores_pre_migration_state(store, tmp_path):
    _seed_legacy_rows(store)
    before = store.get_relationship_state(DEFAULT_PERSONA_ID, "aiocqhttp:42")

    result = store.migrate_person_keys(
        PERSON, ["aiocqhttp:42"], backup_dir=tmp_path, now=NOW
    )
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None

    rollback = store.rollback_person_migration(result["backup_path"])
    assert rollback["ok"] is True
    restored = store.get_relationship_state(DEFAULT_PERSONA_ID, "aiocqhttp:42")
    assert restored is not None
    assert restored.affinity == pytest.approx(before.affinity)
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is None
    assert store.get_interaction_dynamics(DEFAULT_PERSONA_ID, "aiocqhttp:42").message_count == 3
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, "group:1000") is not None


def test_rollback_without_backup_reports_missing(store):
    result = store.rollback_person_migration()
    assert result["ok"] is False
    assert result["reason"] == "no_backup"


def test_list_person_key_candidates_excludes_groups(store):
    _seed_legacy_rows(store)
    candidates = store.list_person_key_candidates()
    keys = {(item["persona_id"], item["user_id"]) for item in candidates}
    assert (DEFAULT_PERSONA_ID, "aiocqhttp:42") in keys
    assert all(not user.startswith("group:") for _, user in keys)
