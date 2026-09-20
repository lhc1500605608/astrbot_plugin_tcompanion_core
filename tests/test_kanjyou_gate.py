from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.contract import ContractV1
from core.kanjyou import ContractVersionError, KanjyouGate
from core.life_state import WeeklySchedule


class StubContract:
    """Minimal contract stub; ``info`` controls the advertised version."""

    def __init__(self, info):
        self._info = info
        self.calls = 0

    async def get_contract_info(self):
        return self._info

    async def get_proactive_context(self, umo, persona_id=None):
        self.calls += 1
        return {"api_version": self._info.get("api_version"), "umo": umo}


class MissingInfoContract:
    async def get_proactive_context(self, umo, persona_id=None):  # pragma: no cover
        return {}


class ExplodingInfoContract:
    async def get_contract_info(self):
        raise RuntimeError("boom")

    async def get_proactive_context(self, umo, persona_id=None):  # pragma: no cover
        return {}


async def test_gate_accepts_api_version_1(store):
    contract = ContractV1(
        store,
        schedule=WeeklySchedule.default_template("p1"),
        clock=lambda: datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
    )
    gate = KanjyouGate(contract)
    info = await gate.ensure_supported()
    assert info["api_version"] == 1
    ctx = await gate.guarded_proactive_context("umo://a", persona_id="p1")
    assert ctx["life_state"]["activity"] == "working"


@pytest.mark.parametrize("bad_version", [0, 2, 3, None, "1"])
async def test_fail_closed_on_mismatched_version(bad_version):
    stub = StubContract({"api_version": bad_version})
    gate = KanjyouGate(stub)
    with pytest.raises(ContractVersionError):
        await gate.ensure_supported()
    assert await gate.guarded_proactive_context("umo://a") is None
    assert stub.calls == 0  # never reached the downstream fetch


async def test_fail_closed_on_missing_method():
    gate = KanjyouGate(MissingInfoContract())
    with pytest.raises(ContractVersionError):
        await gate.ensure_supported()
    assert await gate.guarded_proactive_context("umo://a") is None


async def test_fail_closed_on_info_exception():
    gate = KanjyouGate(ExplodingInfoContract())
    with pytest.raises(ContractVersionError):
        await gate.ensure_supported()
    assert await gate.guarded_proactive_context("umo://a") is None


async def test_fail_closed_on_non_mapping_info():
    gate = KanjyouGate(StubContract("not-a-dict"))
    with pytest.raises(ContractVersionError):
        await gate.ensure_supported()


async def test_override_injection_point_on_contract_v1(store):
    """The acceptance criterion: get_contract_info is overridable for tests."""

    class V2Contract(ContractV1):
        api_version = 2

    gate = KanjyouGate(V2Contract(store))
    with pytest.raises(ContractVersionError):
        await gate.ensure_supported()
    assert await gate.guarded_proactive_context("umo://a") is None


async def test_guarded_context_fails_closed_when_fetch_raises(store):
    contract = ContractV1(store)

    async def boom(umo, persona_id=None):
        raise RuntimeError("db down")

    contract.get_proactive_context = boom  # type: ignore[method-assign]
    gate = KanjyouGate(contract)
    assert await gate.guarded_proactive_context("umo://a") is None
