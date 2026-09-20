"""Frozen contract v1 exposed to downstream consumers.

All methods are ``async`` so a future v2 can await I/O without a signature
break. Every method has a defensive fallback: a storage failure degrades the
returned payload instead of raising into the caller.

Field types / optionality / degradation matrix: see ``docs/CONTRACT.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .life_state import WeeklySchedule, generate_life_state
from .motivation import (
    DEFAULT_OPEN_THREAD_LIMIT,
    build_quota,
    expression_hints,
    fuse_motivation,
    relationship_mode,
)
from .relationship import STAGE_STRANGER, parse_umo
from .store import Store

#: Frozen contract version. Bump only with a new ``docs/CONTRACT.md`` revision.
CONTRACT_API_VERSION = 1

PLUGIN_NAME = "astrbot_plugin_tcompanion_core"
PLUGIN_VERSION = "1.0.0"

#: Persona attributed to an outcome when the caller cannot resolve one.
DEFAULT_PERSONA_ID = "default"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class QuotaView:
    """Proactive-message quota (v1, T3).

    ``allow`` is advisory: companion-core never sends on its own, it only
    tells the downstream decision loop whether budget remains.
    """

    hourly_remaining: int = 0
    daily_remaining: int = 0
    allow: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RelationshipView:
    """Relationship projection for one ``umo``.

    ``closeness`` is the frozen v1 key and mirrors ``affinity``; ``affinity``
    and ``bond`` are additive v1 fields delivered by T2.
    """

    umo: str
    persona_id: str | None
    stage: str
    closeness: float
    affinity: float = 0.0
    bond: bool = False
    degraded: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class ContractV1:
    """Phase 1 implementation of the frozen contract v1.

    ``get_contract_info`` is intentionally overridable (subclass or monkeypatch)
    so the kanjyou fail-closed path can be exercised in tests.
    """

    api_version: int = CONTRACT_API_VERSION

    def __init__(
        self,
        store: Store,
        schedule: WeeklySchedule | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._schedule = schedule
        self._clock = clock or _utcnow

    # -- info --------------------------------------------------------------
    async def get_contract_info(self) -> dict:
        """Return contract metadata. Overridable injection point."""
        try:
            schema_version = self._store.schema_version
        except Exception:
            schema_version = 0
        return {
            "api_version": self.api_version,
            "plugin": PLUGIN_NAME,
            "plugin_version": PLUGIN_VERSION,
            "schema_version": schema_version,
            "capabilities": {
                "life_state": True,
                "schedule": True,
                "relationship": True,
                "motivation": True,
                "open_threads": True,
                "quota": True,
                "proactive": False,
            },
        }

    # -- life state --------------------------------------------------------
    async def get_life_state(self, persona_id: str) -> dict | None:
        """Return today's simplified LifeState, or ``None`` on failure."""
        if not persona_id:
            return None
        try:
            moment = self._clock()
            day = moment.date()
            stored = self._store.get_life_state(persona_id, day.isoformat())
            if stored is not None:
                return {
                    "persona_id": stored["persona_id"],
                    "activity": stored["activity"],
                    "energy": stored["energy"],
                    "scene": stored["scene"],
                    "summary": stored["summary"],
                    "as_of": stored["as_of"],
                    "degraded": False,
                }
            schedule = self._schedule or self._store.load_schedule(persona_id)
            if schedule is None:
                return self._degraded_life_state(persona_id, moment)
            state = generate_life_state(schedule, persona_id, moment)
            return {**state.to_dict(), "degraded": False}
        except Exception:
            return self._degraded_life_state(persona_id, self._clock())

    # -- relationship ------------------------------------------------------
    async def get_relationship(self, umo: str, persona_id: str | None = None) -> dict:
        """Return the frozen v1 relationship structure for ``umo``.

        Pure read (no writes). Group sessions are isolated and never inherit a
        private ``(persona_id, user_id)`` relationship; those return the
        neutral default with ``degraded=True``.
        """
        if not umo:
            return self._relationship_view(umo, persona_id, STAGE_STRANGER, 0.0, False, True)
        try:
            key = parse_umo(umo)
            if key.is_group:
                return self._relationship_view(umo, persona_id, STAGE_STRANGER, 0.0, False, True)
            state = self._store.resolve_relationship_state(key.user_id, persona_id)
        except Exception:
            state = None
        if state is None:
            return self._relationship_view(umo, persona_id, STAGE_STRANGER, 0.0, False, True)
        return self._relationship_view(
            umo, state.persona_id, state.stage, state.affinity, state.bond, False
        )

    @staticmethod
    def _relationship_view(
        umo: str,
        persona_id: str | None,
        stage: str,
        affinity: float,
        bond: bool,
        degraded: bool,
    ) -> dict:
        return RelationshipView(
            umo=umo,
            persona_id=persona_id,
            stage=stage,
            closeness=affinity,
            affinity=affinity,
            bond=bond,
            degraded=degraded,
        ).to_dict()

    # -- proactive context -------------------------------------------------
    async def get_proactive_context(self, umo: str, persona_id: str | None = None) -> dict:
        """Aggregate payload for downstream consumers (frozen v1, T3).

        Pure read: no mutation of state. Every field is resolved independently
        and falls back per-field, so one failing domain never blanks the rest.
        Returns ``api_version`` / ``life_state`` / ``relationship`` /
        ``expression_hints`` / ``motivation`` / ``open_threads`` / ``quota`` /
        ``unanswered_streak`` (plus the v1 echo fields ``umo`` / ``persona_id``
        / ``degraded``).
        """
        moment = self._clock()
        degraded = False

        try:
            key = parse_umo(umo)
            is_group = key.is_group
            user_id = key.user_id
        except Exception:
            is_group = True
            user_id = ""
            degraded = True

        resolved_persona = persona_id
        if not is_group and resolved_persona is None:
            try:
                state = self._store.resolve_relationship_state(user_id)
                if state is not None:
                    resolved_persona = state.persona_id
            except Exception:
                degraded = True

        # life_state (persona-scoped; unavailable without a persona_id)
        life_state: dict | None = None
        if resolved_persona:
            try:
                life_state = await self.get_life_state(resolved_persona)
            except Exception:
                life_state = None
        life_state_ok = life_state is not None

        # relationship + expression hints (per-field fallback)
        try:
            rel = await self.get_relationship(umo, resolved_persona)
        except Exception:
            rel = self._relationship_view(umo, resolved_persona, STAGE_STRANGER, 0.0, False, True)
            degraded = True
        stage = str(rel.get("stage") or STAGE_STRANGER)
        affinity = float(rel.get("affinity") or 0.0)
        bond = bool(rel.get("bond"))
        try:
            relationship = {
                "stage": stage,
                "affinity": affinity,
                "bond": bond,
                "mode": relationship_mode(stage, bond),
            }
        except Exception:
            relationship = None
            degraded = True

        # interaction dynamics (private scopes only)
        streak = 0
        if not is_group:
            try:
                streak = self._store.get_interaction_dynamics(
                    resolved_persona or "", user_id
                ).unanswered_streak
            except Exception:
                degraded = True

        try:
            hints = expression_hints(stage, bond, streak)
        except Exception:
            hints = None
            degraded = True

        # open threads (short labels; group sessions never inherit private ones)
        open_threads: list[str] = []
        if not is_group:
            try:
                rows = self._store.resolve_open_threads(
                    umo, resolved_persona, limit=DEFAULT_OPEN_THREAD_LIMIT
                )
                open_threads = [row["title"] for row in rows if row.get("title")]
            except Exception:
                degraded = True

        # quota (advisory budget for the downstream decision loop)
        quota = QuotaView().to_dict()
        if not is_group:
            try:
                day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
                scope_persona = resolved_persona or ""
                daily_used = self._store.count_proactive_sent(
                    scope_persona, user_id, day_start.isoformat()
                )
                hourly_used = self._store.count_proactive_sent(
                    scope_persona, user_id, (moment - timedelta(hours=1)).isoformat()
                )
                quota = build_quota(daily_used, hourly_used)
            except Exception:
                degraded = True

        # motivation fusion (deterministic; never writes)
        try:
            motivation = fuse_motivation(
                moment=moment,
                stage=stage,
                bond=bond,
                unanswered_streak=streak,
                activity=(life_state or {}).get("activity", ""),
                energy=(life_state or {}).get("energy", 0.0),
                scene=(life_state or {}).get("scene", ""),
                open_threads=tuple(open_threads),
                allow=bool(quota.get("allow")),
            ).to_dict()
        except Exception:
            motivation = {
                "reason": "",
                "score": 0.0,
                "adopted": False,
                "blocked_reason": "error",
                "candidates": [],
            }
            degraded = True

        if not life_state_ok or bool((life_state or {}).get("degraded")):
            degraded = True

        return {
            "api_version": self.api_version,
            "umo": umo,
            "persona_id": resolved_persona,
            "life_state": life_state,
            "relationship": relationship,
            "expression_hints": hints,
            "motivation": motivation,
            "open_threads": open_threads,
            "quota": quota,
            "unanswered_streak": streak,
            "degraded": degraded,
        }

    async def on_proactive_outcome(
        self,
        umo: str,
        *,
        sent: bool,
        reason_code: str,
        replied: bool = False,
        persona_id: str | None = None,
        event_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Record a proactive outcome receipt; update streak/ledger.

        Idempotent: the receipt is deduplicated per ``(persona_id, user_id)``
        by ``event_id`` or, when omitted, by a deterministic
        ``day|sent|reason_code|replied`` bucket. Replays never double-count the
        streak or affinity ledger. Group scopes are isolated and left untouched.
        """
        moment = now or self._clock()
        try:
            key = parse_umo(umo)
        except Exception:
            return {"applied": False, "duplicate": False, "isolated": False, "reason": "bad_umo"}
        if key.is_group:
            return {
                "applied": False,
                "duplicate": False,
                "isolated": True,
                "reason": "group_isolated",
            }

        resolved = persona_id
        if resolved is None:
            try:
                state = self._store.resolve_relationship_state(key.user_id)
                resolved = state.persona_id if state is not None else DEFAULT_PERSONA_ID
            except Exception:
                resolved = DEFAULT_PERSONA_ID

        receipt_key = event_id or (
            f"{moment.date().isoformat()}|{int(bool(sent))}|{reason_code}|{int(bool(replied))}"
        )
        receipt = self._store.log_motivation(
            persona_id=resolved,
            umo=umo,
            user_id=key.user_id,
            kind="proactive_outcome",
            reason=reason_code,
            selected_reason=reason_code,
            adopted=bool(sent),
            blocked_reason="" if sent else reason_code,
            reason_code=reason_code,
            receipt_key=receipt_key,
            now=moment,
        )
        if receipt.get("duplicate"):
            dynamics = self._store.get_interaction_dynamics(resolved, key.user_id)
            return {
                "applied": False,
                "duplicate": True,
                "isolated": False,
                "dynamics": dynamics.to_dict(),
            }

        dynamics = self._store.record_proactive_outcome(
            resolved, key.user_id, sent=bool(sent), replied=bool(replied), now=moment
        )
        return {
            "applied": True,
            "duplicate": False,
            "isolated": False,
            "dynamics": dynamics.to_dict(),
        }

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _degraded_life_state(persona_id: str, moment: datetime) -> dict:
        return {
            "persona_id": persona_id,
            "activity": "",
            "energy": 0.0,
            "scene": "",
            "summary": "",
            "as_of": moment.isoformat(),
            "degraded": True,
        }
