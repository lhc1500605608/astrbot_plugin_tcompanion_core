"""v1.9: read-only consumption of the shared ``identity_map.json``.

Covers the offline Person resolution fallback (TMEAAA-570):

* ``core.identity_map.IdentityMap`` — mtime-cached, fail-closed parsing;
* ``MemoryBridge.resolve_person`` — online bridge wins, shared file is the
  fallback, and both missing/corrupt collapse to a byte-identical v1.8.0 result.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from core.contract import ContractV1
from core.identity_map import (
    IdentityMap,
    normalize_adapter_user_id,
    resolve_identity_map_path,
    resolve_mirror_path,
)
from core.memory_bridge import MemoryBridge
from core.relationship import parse_umo

UMO_A = "aiocqhttp:FriendMessage:67890"
UMO_B = "telegram:FriendMessage:7"
GROUP_UMO = "aiocqhttp:GroupMessage:1000"
WEBCHAT_UMO = "webchat:FriendMessage:webchat!tmemory-smoke!qa368-smoke-1789624808"
PERSON = "person-zhang"
NOW = datetime(2026, 9, 24, 9, 30, tzinfo=timezone.utc)

PAYLOAD = {
    "version": 1,
    "authority": "tmemory",
    "updated_at": "2026-09-24 12:00:00",
    "persons": {PERSON: {"display_name": "", "bindings": [], "updated_at": ""}},
    "index": {"aiocqhttp:67890": PERSON, "telegram:7": PERSON},
}

WEBCHAT_PAYLOAD = {
    **PAYLOAD,
    "index": {"webchat:tmemory-smoke": PERSON},
}


class _IdentityStar:
    """Fake memory plugin exposing ``resolve_person``."""

    def __init__(self, mapping=None, *, raises=None, delay=0.0):
        self._mapping = dict(mapping or {})
        self._raises = raises
        self._delay = delay
        self.calls = 0

    async def resolve_person(self, umo):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        person_id = self._mapping.get(umo, "")
        if not person_id:
            return {}
        parts = str(umo or "").split(":")
        return {
            "person_id": person_id,
            "adapter": parts[0],
            "adapter_user_id": parts[-1],
            "is_group": "group" in (parts[1].lower() if len(parts) > 1 else ""),
        }


class _Metadata:
    def __init__(self, star, activated=True):
        self.star_cls = star
        self.activated = activated


class _Context:
    def __init__(self, metadata=None):
        self._metadata = metadata

    def get_registered_star(self, name):
        return self._metadata


def _bridge(star=None, *, config=None, identity_map=None):
    context = _Context(_Metadata(star) if star is not None else None)
    return MemoryBridge(context, config=config, identity_map=identity_map)


def _write_map(path, payload=PAYLOAD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# -- IdentityMap parsing ---------------------------------------------------
def test_lookup_hits_and_misses(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    assert mapper.lookup("aiocqhttp", "67890") == PERSON
    assert mapper.lookup("telegram", "7") == PERSON
    assert mapper.lookup("aiocqhttp", "00000") is None
    assert mapper.lookup("", "67890") is None
    assert mapper.lookup("aiocqhttp", "") is None


# -- WebChat key normalization (TMEAAA-578) --------------------------------
def test_normalize_adapter_user_id_webchat():
    assert normalize_adapter_user_id("webchat", "webchat!smoke!conv-1") == "smoke"
    # sender id already decoded / unrelated platforms / malformed → unchanged
    assert normalize_adapter_user_id("webchat", "smoke") == "smoke"
    assert normalize_adapter_user_id("aiocqhttp", "webchat!smoke!conv-1") == (
        "webchat!smoke!conv-1"
    )
    assert normalize_adapter_user_id("webchat", "webchat!smoke") == "webchat!smoke"
    assert normalize_adapter_user_id("webchat", "") == ""


def test_lookup_decodes_webchat_session_id(tmp_path):
    """The QA case-4 path: parse_umo → lookup must hit the authority key."""
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", WEBCHAT_PAYLOAD))
    parsed = parse_umo(WEBCHAT_UMO)
    assert parsed.platform == "webchat"
    assert parsed.session_id == "webchat!tmemory-smoke!qa368-smoke-1789624808"
    assert mapper.lookup(parsed.platform, parsed.session_id) == PERSON
    # both the raw sender id and the encoded session id resolve the same Person
    assert mapper.lookup("webchat", "tmemory-smoke") == PERSON


def test_missing_file_is_fail_closed(tmp_path):
    mapper = IdentityMap(tmp_path / "nope.json")
    assert mapper.lookup("aiocqhttp", "67890") is None
    assert mapper.size() == 0


def test_corrupt_file_is_fail_closed(tmp_path):
    path = tmp_path / "identity_map.json"
    path.write_text("{not valid json", encoding="utf-8")
    mapper = IdentityMap(path)
    assert mapper.lookup("aiocqhttp", "67890") is None


def test_version_mismatch_is_fail_closed(tmp_path):
    payload = {**PAYLOAD, "version": 99}
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", payload))
    assert mapper.lookup("aiocqhttp", "67890") is None


def test_wrong_root_type_is_fail_closed(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", ["not", "a", "dict"]))
    assert mapper.lookup("aiocqhttp", "67890") is None


def test_reloads_only_when_mtime_changes(tmp_path):
    path = _write_map(tmp_path / "identity_map.json")
    mapper = IdentityMap(path)
    assert mapper.lookup("aiocqhttp", "67890") == PERSON

    stat = path.stat()
    _write_map(path, {**PAYLOAD, "index": {"aiocqhttp:67890": "person-new"}})
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # unchanged mtime
    assert mapper.lookup("aiocqhttp", "67890") == PERSON  # still cached

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
    assert mapper.lookup("aiocqhttp", "67890") == "person-new"


def test_reload_after_delete_and_recreate(tmp_path):
    path = _write_map(tmp_path / "identity_map.json")
    mapper = IdentityMap(path)
    assert mapper.lookup("aiocqhttp", "67890") == PERSON
    path.unlink()
    assert mapper.lookup("aiocqhttp", "67890") is None
    _write_map(path)
    os.utime(path, ns=(3_000_000_000, 3_000_000_000))
    assert mapper.lookup("aiocqhttp", "67890") == PERSON


def test_resolve_identity_map_path_default(monkeypatch, tmp_path):
    import core.identity_map as mod

    monkeypatch.setattr(mod, "get_shared_data_dir", lambda: tmp_path / "_shared")
    assert resolve_identity_map_path() == tmp_path / "_shared" / "identity_map.json"
    assert resolve_identity_map_path(tmp_path / "x.json") == tmp_path / "x.json"


def test_resolve_mirror_path_default(monkeypatch, tmp_path):
    import core.identity_map as mod

    monkeypatch.setattr(mod, "get_identity_mirror_path", lambda: tmp_path / "p" / "mirror.json")
    assert resolve_mirror_path() == tmp_path / "p" / "mirror.json"
    assert resolve_mirror_path(tmp_path / "x.json") == tmp_path / "x.json"


# -- stored-key resolution (panel, TMEAAA-574) -----------------------------
def test_resolve_key_maps_stored_keys(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    assert mapper.resolve_key("aiocqhttp:67890") == PERSON
    assert mapper.resolve_key("67890") == PERSON
    assert mapper.resolve_key(PERSON) == PERSON
    assert mapper.resolve_key("unknown:1") is None
    assert mapper.resolve_key("group:1") is None
    assert mapper.resolve_key("") is None


def test_resolve_key_normalizes_webchat_session(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", WEBCHAT_PAYLOAD))
    assert mapper.resolve_key("webchat!tmemory-smoke!qa368") == PERSON


# -- local mirror (TMEAAA-574) ---------------------------------------------
def test_mirror_is_synced_and_used_when_shared_missing(tmp_path):
    shared = _write_map(tmp_path / "_shared" / "identity_map.json")
    mirror = tmp_path / "private" / "identity_map.json"
    mapper = IdentityMap(shared, mirror)

    assert mapper.lookup("aiocqhttp", "67890") == PERSON
    assert mirror.exists()

    shared.unlink()  # tmemory gone / standalone: the mirror keeps resolving
    assert mapper.lookup("aiocqhttp", "67890") == PERSON

    fresh = IdentityMap(tmp_path / "_shared" / "identity_map.json", mirror)
    assert fresh.lookup("aiocqhttp", "67890") == PERSON


def test_shared_wins_over_stale_mirror(tmp_path):
    mirror = _write_map(
        tmp_path / "m.json", {**PAYLOAD, "index": {"aiocqhttp:67890": "mirror-person"}}
    )
    shared = _write_map(tmp_path / "s.json")
    mapper = IdentityMap(shared, mirror)
    assert mapper.lookup("aiocqhttp", "67890") == PERSON
    assert json.loads(mirror.read_text(encoding="utf-8"))["index"] == PAYLOAD["index"]


def test_corrupt_shared_falls_back_to_mirror(tmp_path):
    shared = tmp_path / "s.json"
    shared.write_text("{not json", encoding="utf-8")
    mirror = _write_map(tmp_path / "m.json")
    mapper = IdentityMap(shared, mirror)
    assert mapper.lookup("aiocqhttp", "67890") == PERSON


def test_default_construction_has_mirror_injected_path_does_not(tmp_path):
    assert IdentityMap(tmp_path / "s.json").mirror_path is None
    assert IdentityMap(tmp_path / "s.json", tmp_path / "m.json").mirror_path == (
        tmp_path / "m.json"
    )


# -- MemoryBridge offline fallback -----------------------------------------
async def test_online_bridge_wins_over_file(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    star = _IdentityStar({UMO_A: "online-person"})
    bridge = _bridge(star, identity_map=mapper)
    assert await bridge.resolve_person(UMO_A) == "online-person"
    assert star.calls == 1
    assert bridge.stats()["offline_hit"] == 0


async def test_offline_file_fallback_when_online_empty(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    bridge = _bridge(_IdentityStar({}), identity_map=mapper)
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert bridge.stats()["offline_hit"] == 1
    assert bridge.stats()["hit"] == 1


async def test_offline_file_fallback_without_plugin(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    bridge = _bridge(None, identity_map=mapper)
    assert await bridge.resolve_person(UMO_B) == PERSON


async def test_offline_webchat_session_resolves(tmp_path):
    """WebChat offline: encoded UMO session id normalizes to the sender key."""
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", WEBCHAT_PAYLOAD))
    bridge = _bridge(None, identity_map=mapper)
    assert await bridge.resolve_person(WEBCHAT_UMO) == PERSON
    assert bridge.stats()["offline_hit"] == 1


async def test_offline_fallback_is_cached(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    star = _IdentityStar({})
    bridge = _bridge(star, identity_map=mapper)
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert star.calls == 1  # negative online result cached with the hit


async def test_group_scope_skips_file_fallback(tmp_path):
    payload = {**PAYLOAD, "index": {"aiocqhttp:1000": PERSON, "aiocqhttp:group:1000": PERSON}}
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json", payload))
    bridge = _bridge(None, identity_map=mapper)
    assert await bridge.resolve_person(GROUP_UMO) is None


async def test_disabled_bridge_ignores_file(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    bridge = _bridge(None, config={"memory_bridge": {"enabled": False}}, identity_map=mapper)
    assert await bridge.resolve_person(UMO_A) is None
    assert bridge.stats()["offline_hit"] == 0


async def test_online_timeout_falls_back_to_file(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    star = _IdentityStar({UMO_A: "online-person"}, delay=0.2)
    bridge = _bridge(star, config={"memory_bridge": {"timeout_sec": 0.05}}, identity_map=mapper)
    # Even if the online call times out, the shared file still resolves a person.
    assert await bridge.resolve_person(UMO_A) == PERSON
    assert bridge.stats()["timeout"] == 1


# -- byte-identical degradation --------------------------------------------
async def test_missing_file_matches_plain_output(store, tmp_path):
    empty = IdentityMap(tmp_path / "missing.json")

    plain = ContractV1(store, clock=lambda: NOW)
    with_map = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_bridge(None, identity_map=empty)
    )

    assert await with_map.get_proactive_context(UMO_A) == await plain.get_proactive_context(UMO_A)
    assert await with_map.get_relationship(UMO_A) == await plain.get_relationship(UMO_A)
    assert await with_map.get_emotion_context(UMO_A) == await plain.get_emotion_context(UMO_A)
    assert await with_map.get_life_line(UMO_A) == await plain.get_life_line(UMO_A)


async def test_corrupt_file_matches_plain_output(store, tmp_path):
    path = tmp_path / "identity_map.json"
    path.write_text("garbage", encoding="utf-8")
    plain = ContractV1(store, clock=lambda: NOW)
    with_map = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_bridge(None, identity_map=IdentityMap(path))
    )
    assert await with_map.get_proactive_context(UMO_A) == await plain.get_proactive_context(UMO_A)


async def test_file_fallback_echoes_person_id(store, tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    contract = ContractV1(store, memory_bridge=_bridge(None, identity_map=mapper))
    ctx = await contract.get_proactive_context(UMO_A)
    assert ctx["person_id"] == PERSON


# -- capability flag -------------------------------------------------------
async def test_capabilities_expose_identity_map(store):
    info = await ContractV1(store).get_contract_info()
    assert info["capabilities"]["identity_map"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


# -- bridge stored-key resolution (TMEAAA-574) -----------------------------
def test_bridge_resolve_canonical_uses_map(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    bridge = _bridge(None, identity_map=mapper)
    assert bridge.resolve_canonical("67890") == PERSON
    assert bridge.resolve_canonical("aiocqhttp:67890") == PERSON
    assert bridge.resolve_canonical("group:1") == "group:1"
    assert bridge.resolve_canonical("unmapped") == "unmapped"


def test_bridge_resolve_canonical_disabled_bridge_is_self(tmp_path):
    mapper = IdentityMap(_write_map(tmp_path / "identity_map.json"))
    bridge = _bridge(
        None, config={"memory_bridge": {"enabled": False}}, identity_map=mapper
    )
    assert bridge.resolve_canonical("67890") == "67890"
