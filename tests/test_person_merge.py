"""v1.10: map-driven person keys, local mirror and rekey.

Covers TMEAAA-574 (plan TMEAAA-563 rev2, C1):

* ``Store.person_key_views`` / ``/person/keys`` / ``/relationships`` — the
  ``person_key`` comes from the shared identity map (no string heuristics);
* ``ContractV1.plan_person_rekey`` / ``rekey_person_keys`` — mapping-driven,
  idempotent, backed up and reversible;
* ``ContractV1._private_scope`` — the (unchanged) unmigrated-key guard.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.identity import parse_identity_config
from core.identity_map import IdentityMap
from core.relationship import STAGE_FAMILIAR, RelationshipState
from core.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = "astrbot_plugin_tcompanion_core"

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
FALLBACK = "1500605608"
PERSON = "千草酱:1500605608"
UMO = f"aiocqhttp:FriendMessage:{FALLBACK}"
GROUP_UMO = "aiocqhttp:GroupMessage:1000"

INDEX = {"aiocqhttp:1500605608": PERSON}


class _IdentityStar:
    """Fake memory plugin exposing ``resolve_person``."""

    def __init__(self, mapping=None):
        self._mapping = dict(mapping or {})

    async def resolve_person(self, umo):
        if str(umo or "") in self._mapping:
            return {
                "person_id": self._mapping[umo],
                "adapter": "aiocqhttp",
                "adapter_user_id": "",
                "is_group": False,
            }
        return {}


class _Metadata:
    def __init__(self, star):
        self.star_cls = star
        self.activated = True


class _Context:
    def __init__(self, star=None):
        self._metadata = _Metadata(star) if star is not None else None

    def get_registered_star(self, name):
        return self._metadata


def _bridge(mapping=None, *, identity_map=None):
    from core.memory_bridge import MemoryBridge

    return MemoryBridge(
        _Context(_IdentityStar(mapping)), config={}, identity_map=identity_map
    )


def _write_map(tmp_path, index):
    path = tmp_path / "identity_map.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "authority": "tmemory",
                "updated_at": "",
                "persons": {},
                "index": index,
            }
        ),
        encoding="utf-8",
    )
    return path


def _mapped_bridge(tmp_path, index=None, *, mapping=None):
    return _bridge(mapping, identity_map=IdentityMap(_write_map(tmp_path, index or INDEX)))


def _rel(user_id, affinity=0.4):
    return RelationshipState(
        persona_id=DEFAULT_PERSONA_ID,
        user_id=user_id,
        affinity=affinity,
        stage=STAGE_FAMILIAR,
        updated_at=NOW.isoformat(),
    )


# -- store key view (no heuristics) ----------------------------------------
def test_person_key_views_counts_rows_and_recency(store):
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.record_user_message(DEFAULT_PERSONA_ID, FALLBACK, now=NOW, count=3)

    item = next(i for i in store.person_key_views() if i["user_id"] == FALLBACK)
    assert item["rows"] == 2  # one relationship row + one stats row
    assert item["last_active_at"] == NOW.isoformat()
    # The store stays mapping-free and carries no string-heuristic hint.
    assert "person_key" not in item
    assert "suspected_person" not in item
    assert "suspected_reason" not in item


# -- map-driven resolve ----------------------------------------------------
def test_resolve_person_key_uses_map(store, tmp_path):
    contract = ContractV1(store, memory_bridge=_mapped_bridge(tmp_path))
    assert contract.resolve_person_key(FALLBACK) == PERSON
    assert contract.resolve_person_key("aiocqhttp:1500605608") == PERSON
    assert contract.resolve_person_key(PERSON) == PERSON
    assert contract.resolve_person_key("unknown:9") == "unknown:9"
    assert contract.resolve_person_key("group:1000") == "group:1000"
    assert contract.resolve_person_key("") == ""


def test_resolve_person_key_without_map_is_self(store):
    contract = ContractV1(store)
    assert contract.resolve_person_key(FALLBACK) == FALLBACK
    assert contract.resolve_person_key("webchat:someone") == "webchat:someone"


def test_resolve_person_key_normalizes_webchat_session(store, tmp_path):
    contract = ContractV1(
        store, memory_bridge=_mapped_bridge(tmp_path, {"webchat:tester": PERSON})
    )
    assert contract.resolve_person_key("webchat!tester!conv-1") == PERSON


async def test_capabilities_expose_person_merge(store):
    info = await ContractV1(store).get_contract_info()
    assert info["capabilities"]["person_merge"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


# -- config ----------------------------------------------------------------
def test_parse_identity_config_defaults_and_flavours():
    assert parse_identity_config(None).auto_migrate is False
    assert parse_identity_config({}).auto_migrate is False
    assert parse_identity_config({"identity": {"auto_migrate": True}}).auto_migrate is True
    assert parse_identity_config({"auto_migrate": "yes"}).auto_migrate is True
    assert parse_identity_config({"identity": {"auto_migrate": "off"}}).auto_migrate is False


# -- rekey (mapping-driven) ------------------------------------------------
def test_plan_person_rekey_groups_orphans(store, tmp_path):
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.save_relationship_state(_rel(PERSON, 0.03))
    contract = ContractV1(store, memory_bridge=_mapped_bridge(tmp_path))

    plan = contract.plan_person_rekey()
    assert plan == [
        {"persona_id": DEFAULT_PERSONA_ID, "person_id": PERSON, "aliases": [FALLBACK]}
    ]


def test_plan_person_rekey_skips_groups_and_unmapped(store, tmp_path):
    store.save_relationship_state(_rel("group:1000", 0.3))
    store.save_relationship_state(_rel("discord:999", 0.2))
    contract = ContractV1(store, memory_bridge=_mapped_bridge(tmp_path))

    assert contract.plan_person_rekey() == []


def test_rekey_is_dry_then_executes_idempotent_and_rolls_back(
    store, tmp_path, monkeypatch
):
    monkeypatch.setenv("TCOMPANION_DATA_DIR", str(tmp_path))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.record_user_message(DEFAULT_PERSONA_ID, FALLBACK, now=NOW, count=3)
    contract = ContractV1(
        store, clock=lambda: NOW, memory_bridge=_mapped_bridge(tmp_path)
    )

    dry = contract.rekey_person_keys(dry_run=True)
    assert dry["dry_run"] is True and dry["ok"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None

    result = contract.rekey_person_keys(dry_run=False)
    assert result["ok"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is None

    again = contract.rekey_person_keys(dry_run=False)  # idempotent: nothing left
    assert again["ok"] is True
    assert again["plan"] == []

    rollback = store.rollback_person_migration()
    assert rollback["ok"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None


# -- unmigrated-key guard (unchanged) --------------------------------------
async def test_probe_default_reports_without_touching_data(store, caplog):
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge({UMO: PERSON}))

    with caplog.at_level(logging.WARNING):
        await contract.get_relationship(UMO)
        await contract.get_relationship(UMO)  # cached: no second warning

    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None
    warnings = [r for r in caplog.records if "legacy key" in r.getMessage()]
    assert len(warnings) == 1


async def test_probe_skips_when_canonical_has_data(store):
    store.save_relationship_state(_rel(PERSON, 0.2))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    contract = ContractV1(
        store,
        config={"identity": {"auto_migrate": True}},
        clock=lambda: NOW,
        memory_bridge=_bridge({UMO: PERSON}),
    )

    await contract.get_relationship(UMO)

    # Both keys kept: the guard never merges when the canonical already has data.
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None


async def test_auto_migrate_merges_idempotent_and_rolls_back(store, tmp_path, monkeypatch):
    monkeypatch.setenv("TCOMPANION_DATA_DIR", str(tmp_path))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.record_user_message(DEFAULT_PERSONA_ID, FALLBACK, now=NOW, count=3)
    contract = ContractV1(
        store,
        config={"identity": {"auto_migrate": True}},
        clock=lambda: NOW,
        memory_bridge=_bridge({UMO: PERSON}),
    )

    await contract.get_relationship(UMO)
    await contract.get_relationship(UMO)  # idempotent re-run

    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is None
    backups = list((tmp_path / "person_migrations").glob("person_migrate_*.json"))
    assert backups

    rollback = store.rollback_person_migration()
    assert rollback["ok"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None


async def test_probe_fail_closed_on_store_error(store, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "resolve_relationship_state", _boom)
    contract = ContractV1(
        store,
        config={"identity": {"auto_migrate": True}},
        clock=lambda: NOW,
        memory_bridge=_bridge({UMO: PERSON}),
    )

    # The probe must never raise into the read path.
    result = await contract.get_relationship(UMO)
    assert result["umo"] == UMO


# -- panel routes ----------------------------------------------------------
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

    web.request = None
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


def _make_star(star_cls, store, config=None, bridge=None):
    from astrbot.api.star import Context

    star = star_cls(Context(), config=config or {})
    star._store = store
    star.contract = ContractV1(
        store, config=config or {}, clock=lambda: NOW, memory_bridge=bridge
    )
    return star


async def test_api_person_keys_returns_mapped_person_key(star_cls, tmp_path):
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    star = _make_star(star_cls, store, bridge=_mapped_bridge(tmp_path))

    response = await star.api_person_keys()
    assert response["status_code"] == 200
    items = {item["user_id"]: item for item in response["payload"]["items"]}
    assert items[FALLBACK]["person_key"] == PERSON
    assert items[PERSON]["person_key"] == PERSON
    assert "suspected_person" not in items[FALLBACK]
    store.close()


async def test_api_relationships_maps_person_key_and_isolates_groups(star_cls, tmp_path):
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.save_relationship_state(_rel("group:1000", 0.3))
    star = _make_star(star_cls, store, bridge=_mapped_bridge(tmp_path))

    response = await star.api_relationships()
    assert response["status_code"] == 200
    items = {item["user_id"]: item for item in response["payload"]["items"]}
    assert items[FALLBACK]["person_key"] == PERSON
    assert items[FALLBACK]["is_group"] is False
    assert items[PERSON]["person_key"] == PERSON
    assert items["group:1000"]["is_group"] is True
    assert items["group:1000"]["person_key"] == ""
    store.close()


async def test_api_relationships_503_without_store(star_cls):
    store = Store.open(":memory:")
    star = _make_star(star_cls, store)
    star._store = None
    for handler in (star.api_relationships, star.api_person_keys, star.api_person_rekey):
        response = await handler()
        assert response["status_code"] == 503
    store.close()


async def test_api_person_rekey_defaults_to_dry_run(star_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("TCOMPANION_DATA_DIR", str(tmp_path))
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    star = _make_star(star_cls, store, bridge=_mapped_bridge(tmp_path))

    response = await star.api_person_rekey()
    assert response["status_code"] == 200
    assert response["payload"]["dry_run"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is not None
    store.close()


async def test_api_person_rekey_executes_when_asked(star_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("TCOMPANION_DATA_DIR", str(tmp_path))
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    star = _make_star(star_cls, store, bridge=_mapped_bridge(tmp_path))

    async def _body():
        return {"dry_run": False}

    monkeypatch.setattr(star, "_json_body", _body)

    response = await star.api_person_rekey()
    assert response["status_code"] == 200
    assert response["payload"]["dry_run"] is False
    assert response["payload"]["ok"] is True
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, PERSON) is not None
    assert store.get_relationship_state(DEFAULT_PERSONA_ID, FALLBACK) is None
    store.close()
