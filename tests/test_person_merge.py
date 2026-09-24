"""v1.8: person-key judgement, panel aggregation and unmigrated-key guard.

Covers the three deliverables of TMEAAA-564:

* ``Store.judge_person_keys`` / ``person_key_hints`` — read-only clustering of
  legacy keys (canonical tail + same digit tail);
* ``/person/keys`` and ``/relationships`` incremental fields;
* ``ContractV1._private_scope`` detecting a suspected unmigrated key: read-only
  by default, merging only when ``identity.auto_migrate`` is on.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.identity import (
    SUSPECT_REASON_CANONICAL,
    SUSPECT_REASON_SAME_TAIL,
    parse_identity_config,
)
from core.relationship import STAGE_FAMILIAR, RelationshipState
from core.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = "astrbot_plugin_tcompanion_core"

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
FALLBACK = "1500605608"
PERSON = "千草酱:1500605608"
DISCORD = "discord:1500605608"
UMO = f"aiocqhttp:FriendMessage:{FALLBACK}"
GROUP_UMO = "aiocqhttp:GroupMessage:1000"

PERSON_KEY_FIELDS = {
    "persona_id",
    "user_id",
    "rows",
    "last_active_at",
    "suspected_person",
    "suspected_reason",
}


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


def _bridge(mapping):
    from core.memory_bridge import MemoryBridge

    return MemoryBridge(_Context(_IdentityStar(mapping)), config={})


def _rel(user_id, affinity=0.4):
    return RelationshipState(
        persona_id=DEFAULT_PERSONA_ID,
        user_id=user_id,
        affinity=affinity,
        stage=STAGE_FAMILIAR,
        updated_at=NOW.isoformat(),
    )


# -- key judgement (store) -------------------------------------------------
def test_cluster_canonical_tail(store):
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.record_user_message(DEFAULT_PERSONA_ID, FALLBACK, now=NOW, count=1)

    items = {item["user_id"]: item for item in store.judge_person_keys()}
    assert set(items[FALLBACK]) == PERSON_KEY_FIELDS
    assert items[FALLBACK]["suspected_person"] == PERSON
    assert items[FALLBACK]["suspected_reason"] == SUSPECT_REASON_CANONICAL
    assert items[PERSON]["suspected_person"] == PERSON
    assert items[PERSON]["suspected_reason"] == SUSPECT_REASON_CANONICAL


def test_cluster_same_tail_rule_b(store):
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(DISCORD, 0.05))
    store.record_user_message(DEFAULT_PERSONA_ID, PERSON, now=NOW, count=4)

    items = {item["user_id"]: item for item in store.judge_person_keys()}
    assert items[DISCORD]["suspected_person"] == items[PERSON]["suspected_person"]
    assert items[DISCORD]["suspected_reason"] == SUSPECT_REASON_SAME_TAIL
    assert items[PERSON]["suspected_reason"] == SUSPECT_REASON_SAME_TAIL


def test_cluster_ignores_group_and_unique_keys(store):
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.save_relationship_state(_rel("group:1000", 0.3))
    store.save_relationship_state(_rel("webchat:someone", 0.2))

    items = {item["user_id"]: item for item in store.judge_person_keys()}
    # Group keys are never candidates; a lone private key is not suspected.
    assert "group:1000" not in items
    assert items[FALLBACK]["suspected_person"] == ""
    assert items[FALLBACK]["suspected_reason"] == ""


def test_judge_person_keys_counts_rows_and_recency(store):
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.record_user_message(DEFAULT_PERSONA_ID, FALLBACK, now=NOW, count=3)

    item = next(i for i in store.judge_person_keys() if i["user_id"] == FALLBACK)
    assert item["rows"] == 2  # one relationship row + one stats row
    assert item["last_active_at"] == NOW.isoformat()


def test_person_key_hints_only_reports_clusters(store):
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.save_relationship_state(_rel("webchat:someone", 0.2))

    hints = store.person_key_hints()
    assert hints[(DEFAULT_PERSONA_ID, FALLBACK)] == PERSON
    assert hints[(DEFAULT_PERSONA_ID, PERSON)] == PERSON
    assert (DEFAULT_PERSONA_ID, "webchat:someone") not in hints


# -- config ----------------------------------------------------------------
def test_parse_identity_config_defaults_and_flavours():
    assert parse_identity_config(None).auto_migrate is False
    assert parse_identity_config({}).auto_migrate is False
    assert parse_identity_config({"identity": {"auto_migrate": True}}).auto_migrate is True
    assert parse_identity_config({"auto_migrate": "yes"}).auto_migrate is True
    assert parse_identity_config({"identity": {"auto_migrate": "off"}}).auto_migrate is False


async def test_capabilities_expose_person_merge(store):
    info = await ContractV1(store).get_contract_info()
    assert info["capabilities"]["person_merge"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


# -- unmigrated-key guard --------------------------------------------------
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


def _make_star(star_cls, store, config=None):
    from astrbot.api.star import Context

    star = star_cls(Context(), config=config or {})
    star._store = store
    star.contract = ContractV1(store, config=config or {}, clock=lambda: NOW)
    return star


async def test_api_person_keys_returns_enriched_items(star_cls):
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    star = _make_star(star_cls, store)

    response = await star.api_person_keys()
    assert response["status_code"] == 200
    items = {item["user_id"]: item for item in response["payload"]["items"]}
    assert set(items[FALLBACK]) == PERSON_KEY_FIELDS
    assert items[FALLBACK]["suspected_person"] == PERSON
    store.close()


async def test_api_relationships_adds_person_key_and_is_group(star_cls):
    store = Store.open(":memory:")
    store.save_relationship_state(_rel(PERSON, 0.03))
    store.save_relationship_state(_rel(FALLBACK, 0.4))
    store.save_relationship_state(_rel("group:1000", 0.3))
    star = _make_star(star_cls, store)

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
    for handler in (star.api_relationships, star.api_person_keys):
        response = await handler()
        assert response["status_code"] == 503
    store.close()
