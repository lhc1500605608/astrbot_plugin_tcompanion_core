"""Life content (v1.7 · Phase 3-B): schema v8, config, fetch/parse, gating.

All tests run offline: feed parsing uses local string fixtures and every
network seam is injected. No test may reach the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.contract import DEFAULT_PERSONA_ID, ContractV1
from core.life_content import (
    ContentConfig,
    dedupe_key_for,
    is_safe_source_url,
    parse_content_config,
    parse_feed,
    strip_html,
    truncate,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>示例源</title>
    <item>
      <title>城市里的猫</title>
      <link>https://example.com/cats</link>
      <guid>https://example.com/cats</guid>
      <description><![CDATA[<p>街角的<b>猫</b>很亲人，&amp; 常常趴在窗台上晒太阳，这里还有一段很长的正文内容不应该被完整保存下来。</p>]]></description>
    </item>
    <item>
      <title>咖啡笔记</title>
      <link>https://example.com/coffee</link>
      <guid>https://example.com/coffee</guid>
      <description>手冲水温的简单心得</description>
    </item>
  </channel>
</rss>"""

ATOM_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom 示例</title>
  <entry>
    <title>山里的一整天</title>
    <link rel="alternate" href="https://example.com/mountain"/>
    <id>tag:example.com,2026:mountain</id>
    <summary>清晨的雾散得很慢。</summary>
  </entry>
</feed>"""


class _Clock:
    """Mutable clock so tests can advance time across the refresh gate."""

    def __init__(self, moment: datetime = NOW):
        self.now = moment

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def _contract(store, *, config=None, clock=None, fetcher=None, summarizer=None):
    return ContractV1(
        store,
        config=config,
        clock=clock or _Clock(),
        content_fetcher=fetcher,
        content_summarizer=summarizer,
    )


def _enabled_config(**overrides) -> dict:
    section = {
        "content_enabled": True,
        "content_sources": ["https://example.com/feed.xml"],
        "content_topics": [],
        "content_max_items_per_day": 2,
        "content_summarize": False,
        "content_provider_id": "",
        "content_max_chars": 20,
        "content_ttl_days": 14,
    }
    section.update(overrides)
    return {"content": section}


# -- config -----------------------------------------------------------------
def test_parse_content_config_defaults():
    cfg = parse_content_config({})
    assert cfg == ContentConfig()
    assert cfg.enabled is False
    assert cfg.sources == () and cfg.topics == ()
    assert cfg.max_items_per_day == 2 and cfg.max_chars == 80 and cfg.ttl_days == 14


def test_parse_content_config_group_and_flat():
    grouped = parse_content_config(
        {"content": {"content_enabled": True, "content_topics": ["猫", " 咖啡 "]}}
    )
    assert grouped.enabled is True
    assert grouped.topics == ("猫", "咖啡")

    flat = parse_content_config({"content_enabled": True, "content_max_chars": 30})
    assert flat.enabled is True and flat.max_chars == 30


def test_parse_content_config_clamps_items_per_day():
    assert parse_content_config({"content": {"content_max_items_per_day": 99}}).max_items_per_day == 3
    assert parse_content_config({"content": {"content_max_items_per_day": 0}}).max_items_per_day == 1


def test_parse_content_config_bad_values_fall_back():
    cfg = parse_content_config(
        {"content": {"content_max_chars": "oops", "content_ttl_days": None}}
    )
    assert cfg.max_chars == 80 and cfg.ttl_days == 14


# -- text helpers -----------------------------------------------------------
def test_strip_html_and_truncate():
    assert strip_html("<p>hello &amp; <b>world</b></p>") == "hello & world"
    assert truncate("abcdef", 4) == "abc…"
    assert len(truncate("x" * 50, 20)) <= 20
    assert truncate("short", 20) == "short"


def test_is_safe_source_url_rejects_private_and_local():
    assert is_safe_source_url("https://example.com/feed.xml")
    assert not is_safe_source_url("http://localhost/feed")
    assert not is_safe_source_url("http://127.0.0.1/feed")
    assert not is_safe_source_url("http://10.0.0.5/feed")
    assert not is_safe_source_url("http://192.168.1.1/feed")
    assert not is_safe_source_url("http://169.254.1.1/feed")
    assert not is_safe_source_url("file:///etc/passwd")
    assert not is_safe_source_url("")


# -- feed parsing (offline fixtures) ---------------------------------------
def test_parse_feed_rss_fixture():
    items = parse_feed(RSS_FIXTURE)
    assert len(items) == 2
    assert items[0]["title"] == "城市里的猫"
    assert items[0]["guid"] == "https://example.com/cats"
    assert "猫" in items[0]["summary"]


def test_parse_feed_atom_fixture():
    items = parse_feed(ATOM_FIXTURE)
    assert len(items) == 1
    assert items[0]["title"] == "山里的一整天"
    assert items[0]["link"] == "https://example.com/mountain"


def test_parse_feed_malformed_is_silent():
    assert parse_feed("not xml at all") == []
    assert parse_feed("") == []


# -- default-off ------------------------------------------------------------
async def test_default_off_reads_empty_and_refresh_noop_without_network(store):
    called = []

    async def _fetcher(url):  # pragma: no cover - must never run
        called.append(url)
        raise AssertionError("network must not be touched when disabled")

    contract = _contract(store, config={}, fetcher=_fetcher)

    read = await contract.get_life_content(DEFAULT_PERSONA_ID)
    assert read["items"] == [] and read["degraded"] is False

    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result == {
        "applied": False,
        "generated": 0,
        "skipped_reason": "disabled",
        "degraded": False,
    }
    assert called == []
    assert store.last_life_content_refresh(DEFAULT_PERSONA_ID) is None


# -- enabled generation -----------------------------------------------------
async def test_enabled_refresh_generates_short_items_without_full_text(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    contract = _contract(store, config=_enabled_config(content_max_chars=20), fetcher=_fetcher)
    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result["applied"] is True and result["generated"] == 2

    read = await contract.get_life_content(DEFAULT_PERSONA_ID)
    assert len(read["items"]) == 2
    for item in read["items"]:
        assert item["kind"] == "rss"
        assert item["source_ref"]
        assert len(item["summary"]) <= 20
        assert "<" not in item["summary"] and ">" not in item["summary"]
    joined = " ".join(item["summary"] for item in read["items"])
    assert "不应该被完整保存" not in joined


async def test_items_have_expiry(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    contract = _contract(store, config=_enabled_config(content_ttl_days=3), fetcher=_fetcher)
    await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    items = (await contract.get_life_content(DEFAULT_PERSONA_ID))["items"]
    expected = (NOW + timedelta(days=3)).isoformat()
    assert all(item["expires_at"] == expected for item in items)


async def test_topics_generate_then_dedupe(store):
    clock = _Clock()
    contract = _contract(
        store,
        config=_enabled_config(
            content_sources=[], content_topics=["猫", "咖啡"], content_max_items_per_day=3
        ),
        clock=clock,
    )

    first = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert first["generated"] == 2

    clock.advance(hours=3)
    second = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert second["applied"] is False and second["generated"] == 0
    assert second["skipped_reason"] == "empty"
    assert store.count_life_content_today(DEFAULT_PERSONA_ID, NOW.date().isoformat()) == 2


# -- gating -----------------------------------------------------------------
async def test_min_refresh_interval_gate(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    contract = _contract(store, config=_enabled_config(), fetcher=_fetcher)
    await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    again = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert again["skipped_reason"] == "min_interval" and again["applied"] is False


async def test_daily_limit_is_a_noop(store):
    clock = _Clock()
    contract = _contract(
        store,
        config=_enabled_config(
            content_sources=[], content_topics=["猫", "咖啡"], content_max_items_per_day=1
        ),
        clock=clock,
    )
    first = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert first["generated"] == 1

    clock.advance(hours=3)
    second = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert second["skipped_reason"] == "daily_limit" and second["applied"] is False


async def test_no_sources_configured_is_noop(store):
    contract = _contract(store, config=_enabled_config(content_sources=[], content_topics=[]))
    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result["skipped_reason"] == "no_sources"


# -- silent failure / SSRF --------------------------------------------------
async def test_unsafe_sources_are_rejected_without_fetch(store):
    called = []

    async def _fetcher(url):  # pragma: no cover - must never run
        called.append(url)
        return RSS_FIXTURE

    contract = _contract(
        store,
        config=_enabled_config(content_sources=["http://127.0.0.1/feed", "http://localhost/x"]),
        fetcher=_fetcher,
    )
    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result["applied"] is False and result["generated"] == 0
    assert result["degraded"] is True
    assert called == []


async def test_fetch_error_is_silent(store):
    async def _fetcher(url):
        raise RuntimeError("boom")

    contract = _contract(store, config=_enabled_config(), fetcher=_fetcher)
    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result["applied"] is False and result["degraded"] is True
    assert (await contract.get_life_content(DEFAULT_PERSONA_ID))["items"] == []


# -- summarizer seam --------------------------------------------------------
async def test_summarize_without_provider_falls_back_to_truncated(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    contract = _contract(store, config=_enabled_config(content_summarize=True), fetcher=_fetcher)
    await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    items = (await contract.get_life_content(DEFAULT_PERSONA_ID))["items"]
    assert items and all(len(item["summary"]) <= 20 for item in items)


async def test_summarize_error_is_silent(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    async def _summarizer(text, provider_id):
        raise RuntimeError("no provider")

    contract = _contract(
        store,
        config=_enabled_config(content_summarize=True),
        fetcher=_fetcher,
        summarizer=_summarizer,
    )
    result = await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    assert result["generated"] == 2
    items = (await contract.get_life_content(DEFAULT_PERSONA_ID))["items"]
    assert all(len(item["summary"]) <= 20 for item in items)


async def test_summarize_uses_injected_summarizer(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    async def _summarizer(text, provider_id):
        return "一句话概括"

    contract = _contract(
        store,
        config=_enabled_config(content_summarize=True, content_provider_id="cheap"),
        fetcher=_fetcher,
        summarizer=_summarizer,
    )
    await contract.refresh_life_content(DEFAULT_PERSONA_ID)
    items = (await contract.get_life_content(DEFAULT_PERSONA_ID))["items"]
    assert items and all(item["summary"] == "一句话概括" for item in items)


# -- read path --------------------------------------------------------------
async def test_read_filters_kind_and_window(store):
    async def _fetcher(url):
        return RSS_FIXTURE

    clock = _Clock()
    contract = _contract(store, config=_enabled_config(content_sources=[], content_topics=["猫"]), clock=clock)
    await contract.refresh_life_content(DEFAULT_PERSONA_ID)

    clock.advance(days=10)
    recent = await contract.get_life_content(DEFAULT_PERSONA_ID, window=timedelta(hours=1))
    assert recent["items"] == []

    within = await contract.get_life_content(DEFAULT_PERSONA_ID, window=timedelta(days=30))
    assert len(within["items"]) == 1 and within["items"][0]["kind"] == "topic"

    wrong_kind = await contract.get_life_content(DEFAULT_PERSONA_ID, kind="rss")
    assert wrong_kind["items"] == []


async def test_get_life_content_never_raises(store):
    class _BoomStore:
        schema_version = 8

        def purge_expired_life_content(self, *_a, **_k):
            raise RuntimeError("db gone")

        def query_life_content(self, *_a, **_k):
            raise RuntimeError("db gone")

    contract = _contract(_BoomStore(), config=_enabled_config())
    result = await contract.get_life_content(DEFAULT_PERSONA_ID)
    assert result["items"] == [] and result["degraded"] is True


async def test_empty_persona_returns_empty(store):
    contract = _contract(store, config=_enabled_config())
    assert (await contract.get_life_content(""))["items"] == []


# -- store / purge ----------------------------------------------------------
def test_purge_expired_life_content(store):
    past = (NOW - timedelta(days=1)).isoformat()
    future = (NOW + timedelta(days=1)).isoformat()
    store.upsert_life_content(
        "p1", kind="topic", source_ref="topic", summary="旧", dedupe_key="k1",
        expires_at=past, ts=NOW,
    )
    store.upsert_life_content(
        "p1", kind="topic", source_ref="topic", summary="新", dedupe_key="k2",
        expires_at=future, ts=NOW,
    )
    assert store.purge_expired_life_content(NOW) == 1
    rows = store.query_life_content("p1")
    assert [row["summary"] for row in rows] == ["新"]


def test_dedupe_key_is_stable_and_source_scoped():
    item = {"guid": "g1", "title": "t"}
    assert dedupe_key_for("a", item) == dedupe_key_for("a", item)
    assert dedupe_key_for("a", item) != dedupe_key_for("b", item)


@pytest.mark.parametrize("kind", ["topic", "rss"])
def test_store_upsert_and_query_kind(store, kind):
    store.upsert_life_content(
        "p1", kind=kind, source_ref="r", summary="s", dedupe_key=f"{kind}:k", ts=NOW
    )
    assert store.count_life_content_today("p1", NOW.date().isoformat()) == 1
    assert store.last_life_content_refresh("p1") == NOW.isoformat()
    assert store.query_life_content("p1", kind=kind)[0]["summary"] == "s"
