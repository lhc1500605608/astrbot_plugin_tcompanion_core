"""Kanjyou (情感) consumer gate — fail-closed contract validation.

The kanjyou layer must never act on an unknown/mismatched contract version.
It validates ``get_contract_info()['api_version']`` and fails closed: on any
mismatch or malformed payload, ``ensure_supported`` raises and
``guarded_proactive_context`` returns ``None`` (emit nothing) rather than
guessing.

Test seam: the gate accepts any object exposing ``get_contract_info`` — inject
a stub, or subclass :class:`~core.contract.ContractV1` and override the method.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The only contract version this build understands.
SUPPORTED_API_VERSION = 1


class ContractVersionError(RuntimeError):
    """Raised when the upstream contract version is not supported."""


class KanjyouGate:
    """Fail-closed validator wrapping a contract provider."""

    def __init__(self, contract, supported_version: int = SUPPORTED_API_VERSION):
        self._contract = contract
        self._supported_version = supported_version

    async def ensure_supported(self) -> dict:
        """Return contract info, or raise :class:`ContractVersionError`.

        Fail-closed conditions: missing/!callable ``get_contract_info``,
        non-dict payload, missing ``api_version``, or a version mismatch.
        """
        get_info = getattr(self._contract, "get_contract_info", None)
        if not callable(get_info):
            raise ContractVersionError("contract does not expose get_contract_info()")

        try:
            info = await get_info()
        except Exception as exc:  # pragma: no cover - defensive
            raise ContractVersionError(f"get_contract_info() failed: {exc}") from exc

        if not isinstance(info, dict):
            raise ContractVersionError(
                f"contract info must be a mapping, got {type(info).__name__}"
            )

        version = info.get("api_version")
        if version != self._supported_version:
            raise ContractVersionError(
                f"unsupported contract api_version={version!r}, expected {self._supported_version}"
            )
        return info

    async def guarded_proactive_context(
        self, umo: str, persona_id: str | None = None
    ) -> dict | None:
        """Return proactive context, or ``None`` when the contract is invalid."""
        try:
            await self.ensure_supported()
        except ContractVersionError as exc:
            logger.warning("kanjyou fail-closed: %s", exc)
            return None
        try:
            return await self._contract.get_proactive_context(umo, persona_id=persona_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("kanjyou fail-closed on context fetch: %s", exc)
            return None
