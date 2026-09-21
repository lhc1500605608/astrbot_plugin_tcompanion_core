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

from .emotion import (
    EVENT_TYPES,
    STATE_CALM,
    VALENCE_WINDOW_HOURS,
    emotion_snapshot,
    event_delta,
    expression_for,
)
from .life_state import WeeklySchedule, generate_life_state
from .motivation import (
    DEFAULT_OPEN_THREAD_LIMIT,
    OPEN_THREAD_KINDS,
    OPEN_THREAD_STATUS_OPEN,
    OPEN_THREAD_STATUS_STALE,
    OpenThreadConfig,
    build_quota,
    expression_hints,
    fuse_motivation,
    parse_open_thread_config,
    relationship_mode,
    sanitize_thread_title,
    thread_id_for,
)
from .relationship import STAGE_STRANGER, STAGE_UNKNOWN, parse_umo
from .store import Store

#: Frozen contract version. Bump only with a new ``docs/CONTRACT.md`` revision.
CONTRACT_API_VERSION = 1

PLUGIN_NAME = "astrbot_plugin_tcompanion_core"
PLUGIN_VERSION = "1.2.0"

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
        config=None,
    ) -> None:
        self._store = store
        self._schedule = schedule
        self._clock = clock or _utcnow
        self._config = config

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
                # additive v1.1 keys (Phase 2-A/2-C); the map shape is frozen
                "emotion": True,
                "expression": True,
                # additive v1.2 key (Phase 2-B); the map shape stays dict[str, bool]
                "open_threads_followup": True,
            },
            # additive v1.2: the effective open_thread group (defaults applied)
            "open_thread": self._open_thread_config().to_dict(),
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
        / ``degraded``). v1.1 adds the optional keys ``emotion_state`` and
        ``expression``; v1.2 adds the optional ``open_thread_details`` list
        (older clients ignore unknown keys).
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

        # Per-user ledger scope. A private user with no relationship row never
        # gets one from a pure-negative event (affinity floor 0.0), while
        # ``record_emotion_event`` attributes those events to
        # ``DEFAULT_PERSONA_ID`` via ``_resolve_persona``. Reads must use the
        # same fallback or the ledger stays invisible (emotion_state lost).
        scope_persona = resolved_persona or DEFAULT_PERSONA_ID

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
                    scope_persona, user_id
                ).unanswered_streak
            except Exception:
                degraded = True

        try:
            hints = expression_hints(stage, bond, streak)
        except Exception:
            hints = None
            degraded = True

        # emotion ledger + expression decision (v1.1)
        # Private scopes read their own ledger; group scopes never inherit
        # private emotion and are hard-suppressed to the non-intimate modes.
        emotion_state: dict | None = None
        expression: dict | None = None
        emotion_name = ""
        try:
            if is_group:
                decision = expression_for(stage=stage, bond=False, is_group=True)
            else:
                since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
                rows = self._store.list_emotion_events(
                    scope_persona, user_id, since_iso=since, limit=200
                )
                snapshot = emotion_snapshot(rows, now=moment, unanswered_streak=streak)
                emotion_name = snapshot["state"]
                emotion_state = {
                    "state": snapshot["state"],
                    "valence": snapshot["valence"],
                    "last_event": snapshot["last_event"],
                    "as_of": snapshot["as_of"],
                }
                decision = expression_for(
                    state=snapshot["state"],
                    valence=snapshot["valence"],
                    stage=stage,
                    bond=bond,
                    energy=float((life_state or {}).get("energy") or 0.0),
                    unanswered_streak=streak,
                    is_group=False,
                )
            expression = {
                "mode": decision["mode"],
                "style_hints": decision["style_hints"],
                "reason": decision["reason"],
            }
        except Exception:
            emotion_state = None
            expression = None
            emotion_name = ""
            degraded = True

        # open threads (short labels; group sessions never inherit private ones)
        open_threads: list[str] = []
        open_thread_details: list[dict] = []
        if not is_group:
            try:
                cfg = self._open_thread_config()
                if cfg.enabled:
                    # Read-path lifecycle maintenance: no scheduler by design,
                    # so surfacing candidates is where TTL/expiry/LRU advance.
                    self._advance_open_thread_lifecycle(moment, cfg)
                    rows = self._store.resolve_open_threads(
                        umo, resolved_persona, limit=DEFAULT_OPEN_THREAD_LIMIT
                    )
                    open_threads = [row["title"] for row in rows if row.get("title")]
                    open_thread_details = [
                        self._thread_view(row) for row in rows if row.get("title")
                    ]
            except Exception:
                degraded = True

        # quota (advisory budget for the downstream decision loop)
        quota = QuotaView().to_dict()
        if not is_group:
            try:
                day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
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
                open_thread_details=tuple(open_thread_details),
                allow=bool(quota.get("allow")),
                emotion_state=emotion_name,
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
            "open_thread_details": open_thread_details,
            "quota": quota,
            "unanswered_streak": streak,
            "emotion_state": emotion_state,
            "expression": expression,
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

    # -- open threads (v1.2) -----------------------------------------------
    async def record_open_thread(
        self,
        umo: str,
        *,
        label: str,
        kind: str,
        reason: str = "",
        dedupe_key: str | None = None,
        confidence: float = 1.0,
        source: str = "",
        now: datetime | None = None,
    ) -> dict:
        """Record or refresh one unfinished item for a private scope.

        ``label`` is reduced to a short tag (never raw text). Repeated mentions
        of the same ``kind|label`` map to one row and only bump its recency;
        pass a stable ``dedupe_key`` to pin a thread id. Group scopes are
        isolated, unknown ``kind`` values are rejected fail-closed, and a
        storage failure degrades instead of raising.
        """
        moment = now or self._clock()
        base = {
            "thread_id": None,
            "umo": umo,
            "label": "",
            "kind": kind,
            "status": OPEN_THREAD_STATUS_OPEN,
            "isolated": False,
            "applied": False,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "reason": "bad_umo", "degraded": True}
        if key.is_group:
            return {**base, "isolated": True, "reason": "group_isolated", "degraded": False}
        if not self._open_thread_config().enabled:
            return {**base, "reason": "disabled", "degraded": False}
        if kind not in OPEN_THREAD_KINDS:
            return {**base, "reason": "unknown_kind", "degraded": True}
        cleaned = sanitize_thread_title(label)
        if not cleaned:
            return {**base, "reason": "empty_label", "degraded": True}

        resolved = self._resolve_persona(key.user_id)
        thread_id = thread_id_for(kind, cleaned, dedupe_key=dedupe_key)
        try:
            row = self._store.upsert_open_thread(
                thread_id,
                umo,
                resolved,
                cleaned,
                status=OPEN_THREAD_STATUS_OPEN,
                kind=kind,
                source=source,
                confidence=max(0.0, min(1.0, float(confidence or 0.0))),
                dedupe_key=dedupe_key,
                now=moment,
            )
        except Exception:
            return {**base, "reason": "storage_error", "degraded": True}
        return {
            **base,
            "thread_id": thread_id,
            "persona_id": resolved,
            "label": row.get("title") or cleaned,
            "status": row.get("status") or OPEN_THREAD_STATUS_OPEN,
            "applied": True,
            "reason": reason,
            "degraded": False,
        }

    async def get_open_threads(
        self, umo: str, limit: int = DEFAULT_OPEN_THREAD_LIMIT, persona_id: str | None = None
    ) -> list[dict]:
        """Return unfinished items for ``umo`` (open + stale), newest first.

        Advances the lifecycle (TTL/stale/expiry/LRU) before reading. Group
        scopes, a disabled ``open_thread`` section and failures all return
        ``[]``; each item is ``{thread_id, label, kind, status, last_seen,
        followup_count, confidence}`` with short labels only.
        """
        try:
            key = parse_umo(umo)
        except Exception:
            return []
        if key.is_group:
            return []
        cfg = self._open_thread_config()
        if not cfg.enabled:
            return []
        resolved = persona_id or self._resolve_persona(key.user_id)
        self._advance_open_thread_lifecycle(self._clock(), cfg)
        try:
            rows = self._store.list_open_thread_details(
                umo,
                resolved,
                status=(OPEN_THREAD_STATUS_OPEN, OPEN_THREAD_STATUS_STALE),
                limit=limit,
            )
        except Exception:
            return []
        return [self._thread_view(row) for row in rows]

    async def close_open_thread(self, umo: str, thread_id: str, reason: str = "") -> dict:
        """Close one unfinished item (``answered`` / ``expired`` / ``superseded``).

        Group scopes are isolated no-ops; a storage failure degrades. Returns
        ``{thread_id, closed, isolated, reason, degraded}``.
        """
        base = {"thread_id": thread_id, "closed": False, "isolated": False, "reason": reason}
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "reason": "bad_umo", "degraded": True}
        if key.is_group:
            return {**base, "isolated": True, "reason": "group_isolated", "degraded": False}
        if not self._open_thread_config().enabled:
            return {**base, "reason": "disabled", "degraded": False}
        try:
            closed = self._store.close_open_thread(
                thread_id, self._clock(), umo=umo, reason=reason
            )
        except Exception:
            return {**base, "reason": "storage_error", "degraded": True}
        return {**base, "closed": bool(closed), "degraded": False}

    async def mark_thread_followup(
        self, umo: str, thread_id: str, now: datetime | None = None
    ) -> dict:
        """Record that ``thread_id`` was followed up in a proactive message.

        Bumps ``followup_count`` and stamps ``last_followup_ts`` for the
        cooldown/cap gates. Group scopes and unknown ids are no-ops; failures
        degrade. Returns ``{thread_id, updated, followup_count, isolated,
        degraded}``.
        """
        moment = now or self._clock()
        base = {
            "thread_id": thread_id,
            "updated": False,
            "followup_count": 0,
            "last_followup_ts": "",
            "isolated": False,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "reason": "bad_umo", "degraded": True}
        if key.is_group:
            return {**base, "isolated": True, "reason": "group_isolated", "degraded": False}
        if not self._open_thread_config().enabled:
            return {**base, "reason": "disabled", "degraded": False}
        try:
            row = self._store.mark_thread_followup(thread_id, umo=umo, now=moment)
        except Exception:
            return {**base, "reason": "storage_error", "degraded": True}
        if row is None:
            return {**base, "reason": "not_found", "degraded": False}
        return {
            **base,
            "updated": True,
            "followup_count": int(row.get("followup_count") or 0),
            "last_followup_ts": row.get("last_followup_ts") or "",
            "degraded": False,
        }

    # -- emotion ledger (v1.1) ---------------------------------------------
    async def record_emotion_event(
        self,
        umo: str,
        *,
        event_type: str,
        reason: str = "",
        dedupe_key: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Record one emotion event for a private scope; idempotent.

        Group scopes are isolated (``isolated=True``, nothing written) and
        unknown event types are rejected fail-closed. ``dedupe_key`` defaults
        to ``<day>|<event_type>`` (at most one of each per day); the kanjyou
        layer supplies ``proactive:<send_ts>`` / ``msg:<message_id>`` keys so
        the two proactive receipts share one slot and one message settles once.

        Returns ``{applied, duplicate, isolated, event, affinity, stage}``
        plus ``reason`` / ``degraded`` on the degraded paths.
        """
        moment = now or self._clock()
        base = {
            "applied": False,
            "duplicate": False,
            "isolated": False,
            "event": None,
            "affinity": 0.0,
            "stage": STAGE_UNKNOWN,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "reason": "bad_umo", "degraded": True}
        if key.is_group:
            return {**base, "isolated": True, "reason": "group_isolated", "degraded": False}
        if event_type not in EVENT_TYPES:
            return {**base, "reason": "unknown_event_type", "degraded": True}

        resolved = self._resolve_persona(key.user_id)
        receipt_key = dedupe_key or f"{moment.date().isoformat()}|{event_type}"
        try:
            result = self._store.apply_emotion_event(
                resolved,
                key.user_id,
                event_id=receipt_key,
                event_type=event_type,
                delta=event_delta(event_type),
                reason=reason or f"emotion:{event_type}",
                now=moment,
            )
        except Exception:
            return {**base, "reason": "storage_error", "degraded": True}

        state = result.get("state")
        return {
            "applied": bool(result.get("applied")),
            "duplicate": bool(result.get("duplicate")),
            "isolated": False,
            "event": {
                "event_type": event_type,
                "delta": result.get("event_delta", 0.0),
                "ts": moment.isoformat(),
                "day": moment.date().isoformat(),
                "dedupe_key": receipt_key,
            },
            "affinity": float(getattr(state, "affinity", 0.0) or 0.0),
            "stage": str(getattr(state, "stage", STAGE_UNKNOWN) or STAGE_UNKNOWN),
            "persona_id": resolved,
            "degraded": False,
        }

    async def get_emotion_context(self, umo: str, persona_id: str | None = None) -> dict:
        """Derived emotion state for ``umo`` (pure read, no writes).

        Deterministic and bounded: valence decays with a 24h half-life over a
        72h window; the state is picked priority-first (see
        ``core/emotion.py``). Group scopes and failures return a degraded
        neutral state and never leak private emotion.
        """
        moment = self._clock()
        try:
            key = parse_umo(umo)
        except Exception:
            return self._degraded_emotion_context(moment)
        if key.is_group:
            return self._degraded_emotion_context(moment)

        resolved = persona_id or self._resolve_persona(key.user_id)
        try:
            since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
            rows = self._store.list_emotion_events(
                resolved or "", key.user_id, since_iso=since, limit=200
            )
            streak = self._store.get_interaction_dynamics(
                resolved or "", key.user_id
            ).unanswered_streak
            snapshot = emotion_snapshot(rows, now=moment, unanswered_streak=streak)
        except Exception:
            return self._degraded_emotion_context(moment)
        return {**snapshot, "degraded": False}

    async def expression_decision(self, umo: str, persona_id: str | None = None) -> dict:
        """Seven-tier expression decision for ``umo`` (pure read, no writes).

        Private scopes combine the emotion state, the relationship stage and
        the current life energy; group scopes are hard-suppressed to
        ``放松``/``活泼``/``温暖`` with ``warmth <= 0.55``.
        """
        moment = self._clock()
        try:
            key = parse_umo(umo)
        except Exception:
            return self._degraded_expression()
        if key.is_group:
            return self._expression_payload(expression_for(stage=STAGE_STRANGER, is_group=True))

        resolved = persona_id or self._resolve_persona(key.user_id)
        try:
            since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
            rows = self._store.list_emotion_events(
                resolved or "", key.user_id, since_iso=since, limit=200
            )
            streak = self._store.get_interaction_dynamics(
                resolved or "", key.user_id
            ).unanswered_streak
            snapshot = emotion_snapshot(rows, now=moment, unanswered_streak=streak)
            rel = await self.get_relationship(umo, resolved)
            energy = 0.0
            if resolved:
                life = await self.get_life_state(resolved)
                energy = float((life or {}).get("energy") or 0.0)
        except Exception:
            return self._degraded_expression()
        decision = expression_for(
            state=snapshot["state"],
            valence=snapshot["valence"],
            stage=str(rel.get("stage") or STAGE_STRANGER),
            bond=bool(rel.get("bond")),
            energy=energy,
            unanswered_streak=streak,
            is_group=False,
        )
        return self._expression_payload(decision)

    # -- internals ---------------------------------------------------------
    def _open_thread_config(self) -> OpenThreadConfig:
        """Parse the ``open_thread`` group; defaults on any failure.

        Re-parsed on every call because AstrBot hot-reload mutates the injected
        config mapping in place — a cached snapshot would ignore edits until
        the next restart.
        """
        try:
            return parse_open_thread_config(self._config)
        except Exception:
            return OpenThreadConfig()

    def _advance_open_thread_lifecycle(self, moment: datetime, cfg: OpenThreadConfig) -> None:
        """Idempotently advance TTL/stale/expiry/LRU in the read path.

        companion-core deliberately owns no scheduler, so the open-thread read
        paths perform one bounded maintenance pass (three SQL statements); it
        is idempotent for a given ``now`` and never raises into a read.
        """
        try:
            self._store.expire_open_threads(
                moment,
                ttl_days=cfg.ttl_days,
                expire_days=cfg.expire_days,
                max_open=cfg.max_open,
            )
        except Exception:
            pass

    def _resolve_persona(self, user_id: str) -> str:
        """Resolve the persona owning ``user_id`` (falls back to default)."""
        try:
            state = self._store.resolve_relationship_state(user_id)
            return state.persona_id if state is not None else DEFAULT_PERSONA_ID
        except Exception:
            return DEFAULT_PERSONA_ID

    @staticmethod
    def _thread_view(row: dict) -> dict:
        """Project one open-thread row to the public short-label shape."""
        return {
            "thread_id": row.get("thread_id"),
            "label": row.get("title") or "",
            "kind": row.get("kind") or "topic",
            "status": row.get("status") or OPEN_THREAD_STATUS_OPEN,
            "last_seen": row.get("last_seen_ts") or row.get("updated_at") or "",
            "followup_count": int(row.get("followup_count") or 0),
            "confidence": float(row.get("confidence") or 0.0),
        }

    def _expression_payload(self, decision: dict) -> dict:
        return {
            "api_version": self.api_version,
            "mode": decision["mode"],
            "style_hints": decision["style_hints"],
            "reason": decision["reason"],
            "degraded": False,
        }

    def _degraded_expression(self) -> dict:
        return {
            **self._expression_payload(expression_for()),
            "degraded": True,
        }

    def _degraded_emotion_context(self, moment: datetime) -> dict:
        return {
            "state": STATE_CALM,
            "valence": 0.0,
            "recent": [],
            "last_event": None,
            "as_of": moment.isoformat(),
            "degraded": True,
        }

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
