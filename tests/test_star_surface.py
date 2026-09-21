"""Regression: the frozen contract must be reachable through the Star instance.

kanjyou's ``CompanionContextAdapter`` resolves companion-core via
``context.get_registered_star(name).star_cls`` and then ``getattr(star, "<method>")``.
If the contract methods only live on the private ``self.contract`` the whole
integration degrades silently (TMEAAA-454). These tests pin the Star boundary.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.emotion import EVENT_GRATITUDE, EVENT_MISUNDERSTOOD, STATE_HURT

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = "astrbot_plugin_tcompanion_core"

#: Frozen public contract surface the Star must mirror.
CONTRACT_METHODS = frozenset(
    {
        "get_contract_info",
        "get_life_state",
        "get_relationship",
        "get_proactive_context",
        "on_proactive_outcome",
        "record_emotion_event",
        "get_emotion_context",
        "expression_decision",
    }
)


def _stub_astrbot() -> dict[str, types.ModuleType]:
    """Minimal ``astrbot`` API so ``main.py`` can be imported off-device."""
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
    star.contract = ContractV1(
        store, clock=lambda: datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    )
    return star


def test_star_methods_match_frozen_contract(star_cls):
    """Drift guard: the Star surface equals ContractV1's public async API."""
    contract_methods = {
        name
        for name in dir(ContractV1)
        if not name.startswith("_")
        and inspect.iscoroutinefunction(getattr(ContractV1, name, None))
    }
    assert contract_methods == set(CONTRACT_METHODS)


def test_star_exposes_every_contract_method(star_cls, store):
    star = _make_star(star_cls, store)
    public = [name for name in dir(star) if not name.startswith("_")]
    for name in sorted(CONTRACT_METHODS):
        assert name in public, f"Star must expose contract method {name!r}"
        assert callable(getattr(star, name))


async def test_star_delegates_contract_info(star_cls, store):
    star = _make_star(star_cls, store)
    info = await star.get_contract_info()
    assert info["api_version"] == 1
    assert info["plugin"] == PKG


async def test_star_delegates_emotion_roundtrip(star_cls, store):
    """The kanjyou path: record via the Star, then read it back via the Star."""
    star = _make_star(star_cls, store)
    umo = "webchat:FriendMessage:webchat!qa454!probe"

    record = await star.record_emotion_event(
        umo, event_type=EVENT_GRATITUDE, dedupe_key="msg:qa454"
    )
    assert record["applied"] is True

    emotion = await star.get_emotion_context(umo)
    assert emotion["degraded"] is False

    ctx = await star.get_proactive_context(umo)
    assert ctx["emotion_state"] is not None


async def test_star_forwards_keyword_arguments(star_cls, store):
    star = _make_star(star_cls, store)
    seen: dict = {}

    class SpyContract:
        async def record_emotion_event(self, umo, **kwargs):
            seen["umo"] = umo
            seen.update(kwargs)
            return {"applied": True}

    star.contract = SpyContract()
    await star.record_emotion_event(
        "umo://a", event_type=EVENT_GRATITUDE, reason="r", dedupe_key="msg:1"
    )
    assert seen == {
        "umo": "umo://a",
        "event_type": EVENT_GRATITUDE,
        "reason": "r",
        "dedupe_key": "msg:1",
        "now": None,
    }


async def test_star_without_contract_fails_closed(star_cls):
    from astrbot.api.star import Context

    star = star_cls(Context())
    assert star.contract is None
    with pytest.raises(RuntimeError):
        await star.get_proactive_context("umo://a")


async def test_proactive_context_reads_default_scope_without_relationship_row(store):
    """Pure-negative events leave no relationship row but must stay visible."""
    umo = "webchat:FriendMessage:webchat!qa454!negative"
    contract = ContractV1(
        store, clock=lambda: datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    )

    record = await contract.record_emotion_event(
        umo, event_type=EVENT_MISUNDERSTOOD, dedupe_key="msg:neg"
    )
    # The event is persisted even though the affinity floor leaves the ledger
    # untouched (affinity stays 0.0 -> no relationship row).
    assert record["duplicate"] is False
    assert record["persona_id"] == DEFAULT_PERSONA_ID
    assert store.resolve_relationship_state("webchat!qa454!negative") is None

    ctx = await contract.get_proactive_context(umo)
    assert ctx["emotion_state"] is not None
    assert ctx["emotion_state"]["state"] == STATE_HURT
