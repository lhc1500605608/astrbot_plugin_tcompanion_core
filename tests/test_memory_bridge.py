"""Phase 2-E (v1.3) tests: the optional memory bridge + its consumption points.

Covers the bridge itself (fail-closed paths, caching, group privacy) and the
three contract consumption points (`memory` field, `expression_decision` warmth
nudge, `fuse_motivation` ranking hint).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from core.contract import ContractV1
from core.memory_bridge import (
    MEMORY_WARMTH_MAX_DELTA,
    MEMORY_WARMTH_STEP,
    MemoryBridge,
    parse_memory_bridge_config,
)
from core.motivation import (
    MEMORY_HINT_BONUS,
    fuse_motivation,
)

UMO = "aiocqhttp:FriendMessage:67890"
GROUP_UMO = "aiocqhttp:GroupMessage:67890"
NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)

PROFILE = {
    "facets": {"preference": 2, "task_pattern": 1},
    "summary": "喜欢安静，喜欢看电影。",
    "highlights": ["周末常看老电影", "正在准备论文答辩"],
}


class _FakeStar:
    def __init__(self, *, snippets=None, profile=None, delay=0.0, raises=None):
        self._snippets = snippets
        self._profile = profile
        self._delay = delay
        self._raises = raises
        self.calls = {"recall": 0, "profile": 0}

    async def recall_for_prompt(self, umo, query, session_type="private", limit=None):
        self.calls["recall"] += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        return list(self._snippets or [])

    async def get_profile_for_prompt(self, umo, query="", limit=5, session_type="private"):
        self.calls["profile"] += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        return dict(self._profile or {})


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


# -- config parsing --------------------------------------------------------
def test_config_defaults():
    cfg = parse_memory_bridge_config(None)
    assert cfg.enabled is True
    assert cfg.plugin_name == "astrbot_plugin_tmemory"
    assert cfg.timeout_sec == 2.0
    assert cfg.limit == 4
    assert cfg.ttl_min == 5


def test_config_group_and_flat_fallback_and_bounds():
    grouped = parse_memory_bridge_config(
        {"memory_bridge": {"enabled": False, "limit": 9, "timeout_sec": 99, "ttl_min": 0}}
    )
    assert grouped.enabled is False
    assert grouped.limit == 9
    assert grouped.timeout_sec == 10.0  # clamped to the hard ceiling
    assert grouped.ttl_min == 0

    flat = parse_memory_bridge_config({"memory_bridge_enabled": False, "memory_bridge_limit": 2})
    assert flat.enabled is False
    assert flat.limit == 2


# -- bridge reads ----------------------------------------------------------
async def test_fetch_returns_snippets_and_profile():
    star = _FakeStar(snippets=["她提过想看电影", "最近在改论文"], profile=PROFILE)
    bridge = _bridge(star)
    payload = await bridge.fetch(UMO, query="电影 论文", session_type="private")
    assert payload["snippets"] == ["她提过想看电影", "最近在改论文"]
    assert payload["profile"]["facets"] == {"preference": 2, "task_pattern": 1}
    assert payload["profile"]["highlights"] == PROFILE["highlights"]
    assert "as_of" in payload
    assert bridge.stats()["hit"] == 1


async def test_group_scope_never_reads_or_returns_profile():
    star = _FakeStar(snippets=["群里的记忆"], profile=PROFILE)
    bridge = _bridge(star)
    payload = await bridge.fetch(GROUP_UMO, query="电影", session_type="group")
    assert payload["snippets"] == ["群里的记忆"]
    assert "profile" not in payload
    assert star.calls["profile"] == 0


async def test_missing_plugin_degrades_to_none():
    bridge = _bridge(None)
    assert await bridge.fetch(UMO, query="电影") is None
    assert bridge.stats()["degrade"] == 1


async def test_inactive_plugin_degrades_to_none():
    bridge = _bridge(_FakeStar(snippets=["x"]), activated=False)
    assert await bridge.fetch(UMO, query="电影") is None


async def test_disabled_bridge_returns_none_without_resolving():
    star = _FakeStar(snippets=["x"], profile=PROFILE)
    bridge = _bridge(star, config={"memory_bridge": {"enabled": False}})
    assert await bridge.fetch(UMO, query="电影") is None
    assert star.calls == {"recall": 0, "profile": 0}


async def test_timeout_degrades_and_counts():
    star = _FakeStar(snippets=["x"], profile=PROFILE, delay=0.05)
    bridge = _bridge(star, config={"memory_bridge": {"timeout_sec": 0.01}})
    assert await bridge.fetch(UMO, query="电影") is None
    assert bridge.stats()["timeout"] >= 1


async def test_exception_degrades_to_none():
    bridge = _bridge(_FakeStar(raises=RuntimeError("boom")))
    assert await bridge.fetch(UMO, query="电影") is None
    assert bridge.stats()["degrade"] == 1


async def test_older_plugin_without_profile_api_returns_snippets_only():
    class _NoProfile:
        def __init__(self):
            self.calls = 0

        async def recall_for_prompt(self, umo, query, session_type="private", limit=None):
            self.calls += 1
            return ["只有回忆"]

    bridge = _bridge(_NoProfile())
    payload = await bridge.fetch(UMO, query="电影")
    assert payload["snippets"] == ["只有回忆"]
    assert "profile" not in payload


async def test_empty_query_skips_recall_but_still_reads_profile():
    star = _FakeStar(snippets=["不应出现"], profile=PROFILE)
    bridge = _bridge(star)
    payload = await bridge.fetch(UMO, query="")
    assert "snippets" not in payload
    assert payload["profile"]["summary"]
    assert star.calls["recall"] == 0


async def test_cache_avoids_repeat_calls_within_ttl():
    star = _FakeStar(snippets=["记忆"], profile=PROFILE)
    now = [1000.0]
    bridge = _bridge(star, clock=lambda: now[0])
    await bridge.fetch(UMO, query="电影", session_type="private")
    await bridge.fetch(UMO, query="电影", session_type="private")
    assert star.calls["recall"] == 1
    assert star.calls["profile"] == 1

    now[0] += 6 * 60  # past the default 5-minute TTL
    await bridge.fetch(UMO, query="电影", session_type="private")
    assert star.calls["recall"] == 2


async def test_no_data_caches_a_negative_entry():
    star = _FakeStar(snippets=[], profile={})
    bridge = _bridge(star)
    assert await bridge.fetch(UMO, query="电影") is None
    assert await bridge.fetch(UMO, query="电影") is None
    assert star.calls["recall"] == 1
    assert bridge.stats()["degrade"] == 1


# -- contract consumption: memory field ------------------------------------
async def test_no_bridge_emits_no_memory_key(store):
    contract = ContractV1(store, clock=lambda: NOW)
    ctx = await contract.get_proactive_context(UMO)
    assert "memory" not in ctx


async def test_unavailable_bridge_matches_no_bridge_output(store):
    plain = ContractV1(store, clock=lambda: NOW)
    bridged = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(None))
    assert await bridged.get_proactive_context(UMO) == await plain.get_proactive_context(UMO)
    assert await bridged.get_proactive_context(GROUP_UMO) == await plain.get_proactive_context(
        GROUP_UMO
    )


async def test_context_memory_key_with_bridge(store):
    star = _FakeStar(snippets=["她最近在改论文"], profile=PROFILE)
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(star))
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["memory"]["snippets"] == ["她最近在改论文"]
    assert ctx["memory"]["profile"]["facets"]["preference"] == 2
    # hints are ranking-only: gates/lifecycle untouched
    assert ctx["motivation"]["blocked_reason"] == ""
    assert ctx["motivation"]["adopted"] is True


async def test_group_context_memory_has_no_profile(store):
    star = _FakeStar(snippets=["群记忆"], profile=PROFILE)
    contract = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(star))
    ctx = await contract.get_proactive_context(GROUP_UMO)
    assert ctx["memory"]["snippets"] == ["群记忆"]
    assert "profile" not in ctx["memory"]


async def test_capabilities_expose_memory_bridge(store):
    contract = ContractV1(store)
    info = await contract.get_contract_info()
    assert info["capabilities"]["memory_bridge"] is True
    assert all(isinstance(value, bool) for value in info["capabilities"].values())


# -- contract consumption: expression warmth -------------------------------
async def test_expression_warmth_nudged_with_profile(store):
    plain = ContractV1(store, clock=lambda: NOW)
    base = await plain.expression_decision(UMO)

    star = _FakeStar(snippets=[], profile=PROFILE)
    bridged = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(star))
    nudged = await bridged.expression_decision(UMO)

    assert nudged["mode"] == base["mode"]
    delta = nudged["style_hints"]["warmth"] - base["style_hints"]["warmth"]
    assert delta == pytest.approx(MEMORY_WARMTH_STEP)
    assert delta <= MEMORY_WARMTH_MAX_DELTA


async def test_expression_warmth_unchanged_without_profile(store):
    plain = ContractV1(store, clock=lambda: NOW)
    star = _FakeStar(snippets=["记忆"], profile={})
    bridged = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(star))
    assert (await bridged.expression_decision(UMO))["style_hints"] == (
        await plain.expression_decision(UMO)
    )["style_hints"]


async def test_group_expression_ignores_memory(store):
    plain = ContractV1(store, clock=lambda: NOW)
    star = _FakeStar(snippets=["记忆"], profile=PROFILE)
    bridged = ContractV1(store, clock=lambda: NOW, memory_bridge=_bridge(star))
    assert await bridged.expression_decision(GROUP_UMO) == await plain.expression_decision(
        GROUP_UMO
    )


# -- contract consumption: motivation ranking hint -------------------------
def test_memory_hints_bump_ranking_only():
    kwargs = {
        "moment": NOW,
        "stage": "熟悉",
        "unanswered_streak": 0,
        "open_threads": ("论文还没改", "周末电影推荐"),
        "allow": True,
    }
    base = fuse_motivation(**kwargs)
    boosted = fuse_motivation(**kwargs, memory_hints=("正在准备论文答辩",))

    base_by_key = {candidate.key: candidate for candidate in base.candidates}
    boosted_by_key = {candidate.key: candidate for candidate in boosted.candidates}
    paper_key = next(
        key for key, candidate in base_by_key.items() if candidate.label == "论文还没改"
    )
    assert boosted_by_key[paper_key].score == pytest.approx(
        base_by_key[paper_key].score + MEMORY_HINT_BONUS, abs=1e-4
    )
    other_key = next(
        key for key, candidate in base_by_key.items() if candidate.label == "周末电影推荐"
    )
    assert boosted_by_key[other_key].score == base_by_key[other_key].score
    # gates unchanged
    assert boosted.adopted == base.adopted
    assert boosted.blocked_reason == base.blocked_reason


def test_memory_hints_do_not_change_adopted_when_blocked():
    kwargs = {
        "moment": NOW,
        "stage": "熟悉",
        "unanswered_streak": 5,  # blocked regardless of scores
        "open_threads": ("论文还没改",),
        "allow": False,
    }
    result = fuse_motivation(**kwargs, memory_hints=("论文",))
    assert result.adopted is False
    assert result.blocked_reason == "unanswered_streak"
