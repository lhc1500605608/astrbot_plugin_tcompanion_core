from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.contract import ContractV1
from core.life_line import (
    LifeLineConfig,
    in_window,
    infer_sleep_window,
    meal_view,
    parse_life_line_config,
    parse_window,
    synthesize_diary,
)
from core.life_state import LifeState
from core.motivation import build_quota, fuse_motivation
from core.weather import WeatherClient, weather_text

UMO = "aiocqhttp:FriendMessage:67890"
GROUP_UMO = "aiocqhttp:GroupMessage:67890"


def _clock(moment):
    return lambda: moment


# -- config -----------------------------------------------------------------
def test_parse_life_line_config_defaults():
    cfg = parse_life_line_config(None)
    assert cfg == LifeLineConfig()
    assert cfg.enabled is True
    assert cfg.city == ""
    assert cfg.quiet_hours == "23:00-07:30"
    assert cfg.proactive_opt_in is False


def test_parse_life_line_config_nested_and_flat():
    nested = parse_life_line_config(
        {"life_line": {"life_line_enabled": False, "life_city": "北京", "quiet_hours": "22:00-06:00"}}
    )
    assert nested.enabled is False
    assert nested.city == "北京"
    assert nested.quiet_hours == "22:00-06:00"

    flat = parse_life_line_config({"life_line_enabled": True, "life_city": "上海"})
    assert flat.enabled is True
    assert flat.city == "上海"

    malformed = parse_life_line_config({"life_line": "not-a-mapping"})
    assert malformed == LifeLineConfig()


# -- windows ----------------------------------------------------------------
def test_parse_window_and_wrap_aware_membership():
    assert parse_window("23:00-07:30") == (1380, 450)
    assert parse_window("bad") is None
    assert parse_window("07:00-07:00") is None
    assert in_window(1410, (1380, 450)) is True  # 23:30
    assert in_window(60, (1380, 450)) is True  # 01:00
    assert in_window(720, (1380, 450)) is False  # 12:00


def test_meal_view_in_window_and_next():
    windows = parse_life_line_config(None).meal_windows()
    inside = meal_view(12 * 60, windows)
    assert inside["slot"] == "lunch" and inside["in_window"] is True
    upcoming = meal_view(9 * 60, windows)
    assert upcoming["slot"] == "lunch" and upcoming["in_window"] is False


# -- sleep inference --------------------------------------------------------
def test_infer_sleep_window_default_on_insufficient_samples():
    assert infer_sleep_window([]) == (1380, 450, "default")
    sparse = ["2026-09-20T10:00:00+00:00"] * 5
    assert infer_sleep_window(sparse) == (1380, 450, "default")


def test_infer_sleep_window_from_histogram():
    stamps: list[str] = []
    for offset in range(4):
        day = f"2026-09-{17 + offset:02d}"
        for hour in range(8, 23):
            stamps.append(f"{day}T{hour:02d}:30:00+00:00")
    onset, wake, source = infer_sleep_window(stamps)
    assert source == "inferred"
    assert (onset, wake) == (1380, 480)  # 23:00 -> 08:00


# -- weather ----------------------------------------------------------------
async def _stub_fetcher(url: str) -> dict:
    if "search" in url:
        return {"results": [{"latitude": 39.9, "longitude": 116.4}]}
    return {"current": {"temperature_2m": 21.5, "weather_code": 3, "precipitation": 0.2}}


async def test_weather_client_success_and_ttl_cache():
    calls: list[str] = []

    async def fetcher(url):
        calls.append(url)
        return await _stub_fetcher(url)

    client = WeatherClient(city="北京", fetcher=fetcher)
    first = await client.get()
    assert first == {"code": 3, "temp": 21.5, "precip": 0.2, "text": "阴", "city": "北京"}
    assert await client.get() == first
    assert len(calls) == 2  # geocode + forecast, then served from cache
    client.clear_cache()
    await client.get()
    assert len(calls) == 4


async def test_weather_client_fail_closed():
    async def boom(url):
        raise RuntimeError("no network")

    client = WeatherClient(city="北京", fetcher=boom)
    assert await client.get() is None
    assert await WeatherClient(city="").get() is None


def test_weather_text_unknown_code():
    assert weather_text(3) == "阴"
    assert weather_text(9999) == ""


# -- motivation gate --------------------------------------------------------
def test_fuse_motivation_quiet_priority():
    night = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
    quiet = fuse_motivation(moment=night, allow=False, quiet=True).to_dict()
    assert quiet["blocked_reason"] == "quiet_hours"
    assert quiet["adopted"] is False
    streak = fuse_motivation(
        moment=night, allow=False, quiet=True, unanswered_streak=5
    ).to_dict()
    assert streak["blocked_reason"] == "unanswered_streak"
    quota = fuse_motivation(moment=night, allow=False, quiet=False).to_dict()
    assert quota["blocked_reason"] == "quota"


# -- lifecycle shape --------------------------------------------------------
def test_life_state_optional_fields_are_omitted_by_default():
    degraded = LifeState.degraded("p1", as_of="2026-09-21T00:00:00+00:00").to_dict()
    assert degraded == {
        "persona_id": "p1",
        "activity": "",
        "energy": 0.0,
        "scene": "",
        "summary": "",
        "as_of": "2026-09-21T00:00:00+00:00",
    }
    enriched = LifeState(
        persona_id="p1",
        activity="a",
        energy=0.1,
        scene="s",
        summary="m",
        as_of="x",
        weather={"code": 0},
        quiet=False,
    ).to_dict()
    assert enriched["weather"] == {"code": 0}
    assert enriched["quiet"] is False


def test_synthesize_diary_is_deterministic_and_text_free():
    diary = synthesize_diary(
        "2026-09-20", sleep_window=(1380, 450), meals=["lunch"], activity="工作", mood="平静"
    )
    assert diary["day"] == "2026-09-20"
    assert "23:00" in diary["summary"]
    assert "午餐" in diary["summary"]
    assert "工作" in diary["summary"]
    assert diary["mood"] == "平静"
    assert synthesize_diary("2026-09-20") == synthesize_diary("2026-09-20")


# -- contract: identity when disabled ---------------------------------------
V1_FIELDS = {
    "api_version",
    "umo",
    "persona_id",
    "life_state",
    "relationship",
    "expression_hints",
    "motivation",
    "open_threads",
    "open_thread_details",
    "quota",
    "unanswered_streak",
    "emotion_state",
    "expression",
    "degraded",
}


async def test_disabled_life_line_matches_v1_3_0(store):
    now = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    contract = ContractV1(store, clock=_clock(now), config={"life_line": {"enabled": False}})
    ctx = await contract.get_proactive_context(UMO)
    assert "life_detail" not in ctx
    assert set(ctx) == V1_FIELDS
    assert ctx["quota"] == build_quota(0, 0)
    assert ctx["motivation"]["blocked_reason"] == ""
    assert ctx["motivation"]["adopted"] is True


async def test_life_detail_present_private_stripped_group(store):
    now = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    contract = ContractV1(store, clock=_clock(now))
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["life_detail"]["quiet"] is False
    assert set(ctx["life_detail"]) == {"weather", "meal", "sleep", "quiet", "diary"}

    group = await contract.get_proactive_context(GROUP_UMO)
    assert "life_detail" not in group


async def test_group_life_line_is_isolated(store):
    contract = ContractV1(store, clock=_clock(datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)))
    line = await contract.get_life_line(GROUP_UMO)
    assert line["isolated"] is True
    assert line["weather"] is None and line["meal"] is None and line["sleep"] is None
    assert await contract.get_diary(GROUP_UMO) is None


# -- contract: quiet suppression --------------------------------------------
async def test_quiet_hours_suppresses_proactive(store):
    night = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
    contract = ContractV1(store, clock=_clock(night))
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["life_detail"]["quiet"] is True
    assert ctx["quota"]["allow"] is False
    assert ctx["motivation"]["blocked_reason"] == "quiet_hours"
    assert ctx["motivation"]["adopted"] is False


async def test_quiet_hours_opt_in_exempts(store):
    night = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
    contract = ContractV1(
        store, clock=_clock(night), config={"life_line": {"proactive_opt_in": True}}
    )
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["life_detail"]["quiet"] is False
    assert ctx["quota"]["allow"] is True


async def test_quiet_hours_recent_interaction_exempts(store):
    night = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
    store.record_user_message("default", "67890", now=night - timedelta(minutes=3))
    contract = ContractV1(store, clock=_clock(night))
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["life_detail"]["quiet"] is False
    assert ctx["quota"]["allow"] is True


# -- contract: life line reads ----------------------------------------------
async def test_get_life_line_shape_and_sleep(store):
    now = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    contract = ContractV1(store, clock=_clock(now))
    line = await contract.get_life_line(UMO)
    assert line["api_version"] == 1
    assert line["day"] == "2026-09-21"
    assert line["sleep"]["window"] == "23:00-07:30"
    assert line["sleep"]["source"] == "default"
    assert line["quiet"] is False
    assert {"weather", "meal", "sleep", "quiet", "diary", "isolated", "degraded"} <= set(line)


async def test_meal_event_recorded_in_window(store):
    morning = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    contract = ContractV1(store, clock=_clock(morning))
    line = await contract.get_life_line(UMO)
    assert line["meal"]["slot"] == "breakfast"
    assert line["meal"]["in_window"] is True
    rows = store.list_life_events("default", "67890", day="2026-09-21", kind="meal")
    assert [row["dedupe_key"] for row in rows] == ["meal:breakfast:2026-09-21"]


async def test_diary_synthesized_without_llm(store):
    now = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    store.upsert_sleep_window(
        "default", "67890", "2026-09-20", start_min=1380, end_min=450, source="default"
    )
    store.insert_life_event(
        "default",
        "67890",
        kind="meal",
        dedupe_key="meal:lunch:2026-09-20",
        ts=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    contract = ContractV1(store, clock=_clock(now))
    ctx = await contract.get_proactive_context(UMO)
    diary = ctx["life_detail"]["diary"]
    assert diary is not None
    assert diary["day"] == "2026-09-20"
    assert "23:00" in diary["summary"] and "午餐" in diary["summary"]
    assert diary["mood"]

    again = await contract.get_diary(UMO, day="2026-09-20")
    assert again["summary"] == diary["summary"]


async def test_get_diary_none_when_disabled(store):
    contract = ContractV1(store, config={"life_line": {"enabled": False}})
    assert await contract.get_diary(UMO) is None


async def test_weather_dimension_via_injected_client(store):
    now = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    client = WeatherClient(fetcher=_stub_fetcher)
    contract = ContractV1(
        store,
        clock=_clock(now),
        config={"life_line": {"life_city": "北京"}},
        weather_client=client,
    )
    ctx = await contract.get_proactive_context(UMO)
    assert ctx["life_detail"]["weather"]["code"] == 3
    assert ctx["life_detail"]["weather"]["temp"] == 21.5

    # No city -> dimension off even with a client available.
    off = ContractV1(store, clock=_clock(now), weather_client=client)
    assert (await off.get_proactive_context(UMO))["life_detail"]["weather"] is None
