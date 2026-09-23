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
    emotion_state,
    event_delta,
    expression_for,
)
from .group import (
    GroupConfig,
    activity_level,
    evaluate_participation,
    member_key_for,
    parse_group_config,
    topic_age_min,
)
from .growth import (
    GrowthConfig,
    derive_drift,
    derive_level,
    derive_traits,
    derive_xp,
    growth_available,
    parse_growth_config,
    with_growth_drift,
)
from .life_line import (
    QUIET_INTERACTION_GRACE_MIN,
    SLEEP_INFER_DAYS,
    LifeLineConfig,
    format_minutes,
    in_window,
    infer_sleep_window,
    meal_view,
    parse_life_line_config,
    synthesize_diary,
)
from .life_state import WeeklySchedule, generate_life_state
from .memory_bridge import MEMORY_WARMTH_MAX_DELTA, MEMORY_WARMTH_STEP
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
    time_window,
)
from .relationship import STAGE_STRANGER, STAGE_UNKNOWN, parse_umo
from .store import Store
from .weather import WeatherClient

#: Frozen contract version. Bump only with a new ``docs/CONTRACT.md`` revision.
CONTRACT_API_VERSION = 1

PLUGIN_NAME = "astrbot_plugin_tcompanion_core"
PLUGIN_VERSION = "1.6.0"

#: Persona attributed to an outcome when the caller cannot resolve one.
DEFAULT_PERSONA_ID = "default"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value) -> datetime | None:
    """Parse an ISO timestamp to an aware datetime (``None`` when invalid)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
        memory_bridge=None,
        weather_client=None,
    ) -> None:
        self._store = store
        self._schedule = schedule
        self._clock = clock or _utcnow
        self._config = config
        self._memory_bridge = memory_bridge
        # v1.4 life line: an injected client (tests/stub) wins; otherwise one is
        # built lazily from the config and re-built when its signature changes.
        self._injected_weather = weather_client
        self._weather_client = weather_client
        self._weather_key: tuple | None = None

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
                # additive v1.3 key (Phase 2-E); the map shape stays dict[str, bool]
                "memory_bridge": True,
                # additive v1.4 key (Phase 2-D); the map shape stays dict[str, bool]
                "life_line": True,
                # additive v1.5 key; the map shape stays dict[str, bool]
                "identity_binding": True,
                # additive v1.6 keys (Phase 3-A/3-C); the map shape stays dict[str, bool]
                "group_aware": True,
                "growth": True,
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
        private ``(persona_id, person_id)`` relationship; those return the
        neutral default with ``degraded=True``.
        """
        if not umo:
            return self._relationship_view(umo, persona_id, STAGE_STRANGER, 0.0, False, True)
        try:
            key = parse_umo(umo)
            if key.is_group:
                return self._relationship_view(umo, persona_id, STAGE_STRANGER, 0.0, False, True)
            scope, _ = await self._private_scope(key, umo)
            state = self._store.resolve_relationship_state(scope, persona_id)
            if state is None:
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

        Pure read of *business* state. Every field is resolved independently and
        falls back per-field, so one failing domain never blanks the rest. The
        only writes are the idempotent read-path maintenance passes (open-thread
        lifecycle; v1.4 sleep-window/meal-event/diary synthesis), because core
        owns no scheduler.
        Returns ``api_version`` / ``life_state`` / ``relationship`` /
        ``expression_hints`` / ``motivation`` / ``open_threads`` / ``quota`` /
        ``unanswered_streak`` (plus the v1 echo fields ``umo`` / ``persona_id``
        / ``degraded``). v1.1 adds the optional keys ``emotion_state`` and
        ``expression``; v1.2 adds the optional ``open_thread_details`` list
        (older clients ignore unknown keys) and v1.3 the optional ``memory``
        payload (``snippets`` + ``profile``; group scopes get ``snippets`` only).
        v1.4 adds the optional ``life_detail`` (weather/meal/sleep/quiet/diary)
        for private scopes — absent when the section is disabled or isolated —
        and may report ``quota.allow=false`` +
        ``motivation.blocked_reason="quiet_hours"`` during quiet hours.
        v1.5 adds the optional ``person_id`` echo for private scopes (the
        authoritative Person the relationship/emotion/life line is keyed by);
        it is omitted when the identity bridge cannot resolve one, in which
        case the key is ``parse_umo().user_id`` (v1.4.0 behaviour).
        """
        moment = self._clock()
        degraded = False

        person_id = ""
        try:
            key = parse_umo(umo)
            is_group = key.is_group
            if is_group:
                user_id = key.user_id
            else:
                user_id, person_id = await self._private_scope(key, umo)
        except Exception:
            is_group = True
            user_id = ""
            degraded = True

        resolved_persona = persona_id
        if not is_group and resolved_persona is None:
            try:
                state = self._store.resolve_relationship_state(user_id)
                if state is None and person_id:
                    state = self._store.resolve_relationship_state(key.user_id)
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

        # life line (v1.4; private scopes only — group scopes get nothing)
        cfg = self._life_line_config()
        life_detail: dict | None = None
        quiet = False
        if cfg.enabled and not is_group:
            try:
                life_detail = await self._life_detail(scope_persona, user_id, moment, cfg)
                quiet = bool(life_detail.get("quiet"))
            except Exception:
                life_detail = None
                quiet = False
            if quiet:
                # Quiet hours hard-suppress autonomous outreach (D3): the quota
                # is reported exhausted and the motivation is blocked.
                quota = {**quota, "allow": False}

        # group understanding (v1.6; group scopes only — private keys stay absent)
        group_block: dict | None = None
        participation_block: dict | None = None
        if is_group:
            try:
                gctx = self._group_context(umo, moment, stamp=False)
                if gctx is not None:
                    group_block = gctx.get("group")
                    participation_block = gctx.get("participation")
            except Exception:
                degraded = True

        # optional memory bridge payload (v1.3; group scopes get snippets only)
        memory = await self._memory_payload(
            umo,
            is_group=is_group,
            moment=moment,
            life_state=life_state,
            stage=stage,
            open_threads=open_threads,
        )
        memory_hints = self._memory_hints(memory)

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
                memory_hints=memory_hints,
                quiet=quiet,
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

        result = {
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
        # Optional v1.5 key: the resolved Person identity (private only, echoed
        # back). Absent for group scopes and when the bridge cannot resolve one
        # (then the output stays byte-identical to v1.4.0).
        if person_id:
            result["person_id"] = person_id
        # Optional v1.4 key: present only for an enabled private life line
        # (absent when disabled, for group scopes, or on failure).
        if life_detail is not None:
            result["life_detail"] = life_detail
        # Optional v1.3 key: present only when the memory bridge returned data
        # (absent for no bridge / plugin missing / timeout / error / no memory).
        if memory is not None:
            result["memory"] = memory
        # Optional v1.6 keys: group understanding + advisory participation gate
        # (group scopes only; absent when the section is disabled or on failure,
        # so private-only keys above stay absent for groups too).
        if group_block is not None:
            result["group"] = group_block
        if participation_block is not None:
            result["participation"] = participation_block
        return result

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

        Idempotent: the receipt is deduplicated per ``(persona_id, person_id)``
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

        scope, _ = await self._private_scope(key, umo)
        resolved = persona_id or self._resolve_persona(scope, legacy=key.user_id)

        receipt_key = event_id or (
            f"{moment.date().isoformat()}|{int(bool(sent))}|{reason_code}|{int(bool(replied))}"
        )
        receipt = self._store.log_motivation(
            persona_id=resolved,
            umo=umo,
            user_id=scope,
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
            dynamics = self._store.get_interaction_dynamics(resolved, scope)
            return {
                "applied": False,
                "duplicate": True,
                "isolated": False,
                "dynamics": dynamics.to_dict(),
            }

        dynamics = self._store.record_proactive_outcome(
            resolved, scope, sent=bool(sent), replied=bool(replied), now=moment
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

        scope, _ = await self._private_scope(key, umo)
        resolved = self._resolve_persona(scope, legacy=key.user_id)
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
        if persona_id:
            resolved = persona_id
        else:
            scope, _ = await self._private_scope(key, umo)
            resolved = self._resolve_persona(scope, legacy=key.user_id)
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

        scope, _ = await self._private_scope(key, umo)
        resolved = self._resolve_persona(scope, legacy=key.user_id)
        receipt_key = dedupe_key or f"{moment.date().isoformat()}|{event_type}"
        try:
            result = self._store.apply_emotion_event(
                resolved,
                scope,
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

        scope, _ = await self._private_scope(key, umo)
        resolved = persona_id or self._resolve_persona(scope, legacy=key.user_id)
        try:
            since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
            rows = self._store.list_emotion_events(
                resolved or "", scope, since_iso=since, limit=200
            )
            streak = self._store.get_interaction_dynamics(
                resolved or "", scope
            ).unanswered_streak
            snapshot = emotion_snapshot(rows, now=moment, unanswered_streak=streak)
        except Exception:
            return self._degraded_emotion_context(moment)
        return {**snapshot, "degraded": False}

    async def expression_decision(self, umo: str, persona_id: str | None = None) -> dict:
        """Seven-tier expression decision for ``umo`` (pure read, no writes).

        Private scopes combine the emotion state, the relationship stage and
        the current life energy; group scopes are hard-suppressed to
        ``放松``/``活泼``/``温暖`` with ``warmth <= 0.55``. When the memory
        bridge surfaces a user profile the ``style_hints["warmth"]`` is nudged
        up by at most +0.05 (never above the mode's base + 0.05, never changing
        ``mode``); without memory the result is unchanged. A v1.6 growth drift
        (``+0.00``~``drift_cap``, capped at ``0.05``) is then added on top when
        the ``growth`` section is enabled; it also never changes ``mode``.
        """
        moment = self._clock()
        try:
            key = parse_umo(umo)
        except Exception:
            return self._degraded_expression()
        if key.is_group:
            return self._expression_payload(expression_for(stage=STAGE_STRANGER, is_group=True))

        scope, _ = await self._private_scope(key, umo)
        resolved = persona_id or self._resolve_persona(scope, legacy=key.user_id)
        try:
            since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
            rows = self._store.list_emotion_events(
                resolved or "", scope, since_iso=since, limit=200
            )
            streak = self._store.get_interaction_dynamics(
                resolved or "", scope
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
        decision = await self._nudge_warmth_with_memory(decision, umo)
        decision = await self._nudge_warmth_with_growth(decision, scope, resolved or "", moment)
        return self._expression_payload(decision)

    # -- group understanding (v1.6) ----------------------------------------
    async def record_group_activity(
        self,
        umo: str,
        *,
        member_id: str | None = None,
        topic: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Record bounded group activity counters (v1.6, group scopes only).

        Stores only counts, timestamps and an optional sanitized short ``topic``
        label — never message text. ``member_id`` is reduced to a **local**
        member key ``group:<session>#<member>`` and never merged with a private
        ``person`` or aggregated across groups. Private scopes are a no-op
        (``isolated=True``), as is a disabled ``group`` section.
        Returns ``{applied, isolated, group, degraded}``.
        """
        moment = now or self._clock()
        base = {"applied": False, "isolated": False, "group": None, "degraded": False}
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "reason": "bad_umo", "degraded": True}
        if not key.is_group:
            return {**base, "isolated": True, "reason": "private_isolated"}
        cfg = self._group_config()
        if not cfg.enabled:
            return {**base, "isolated": True, "reason": "disabled"}
        try:
            clean_topic = sanitize_thread_title(topic) if topic else ""
            self._store.bump_group_activity(
                umo, topic=clean_topic or None, now=moment
            )
            if cfg.member_tracking_enabled and member_id:
                member_key = member_key_for(key.user_id, member_id)
                if member_key:
                    self._store.bump_group_member(umo, member_key, now=moment)
        except Exception:
            return {**base, "reason": "storage_error", "degraded": True}
        view = self._group_context(umo, moment, member_id=member_id, stamp=False)
        return {
            **base,
            "applied": True,
            "isolated": False,
            "group": (view or {}).get("group"),
        }

    async def get_group_context(
        self, umo: str, persona_id: str | None = None, *, member_id: str | None = None
    ) -> dict:
        """Group understanding + advisory participation gate (v1.6).

        Group → ``{api_version, umo, is_group: True, group, participation,
        member, degraded}``; private or a disabled ``group`` section →
        ``{is_group: False/True, isolated: True, ...}`` (empty, fail-closed).
        ``persona_id`` is accepted for signature symmetry and ignored (groups are
        never persona- or person-scoped). ``member_id`` only refines the ``member``
        block. When ``participation.allow`` is true this call **consumes** the
        advisory slot (cooldown/hourly windows advance); it is the decision
        endpoint, and repeated calls inside the window report ``cooldown``.
        """
        moment = self._clock()
        base = {
            "api_version": self.api_version,
            "umo": umo,
            "persona_id": None,
            "is_group": False,
            "isolated": True,
            "group": None,
            "participation": None,
            "member": None,
            "degraded": False,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "degraded": True}
        if not key.is_group:
            return base
        try:
            view = self._group_context(umo, moment, member_id=member_id, stamp=True)
        except Exception:
            return {**base, "is_group": True, "degraded": True}
        if view is None:
            return {**base, "is_group": True}
        return view

    # -- growth (v1.6) ------------------------------------------------------
    async def get_growth_context(self, umo: str, persona_id: str | None = None) -> dict:
        """Deterministically derived growth for a private scope (v1.6).

        Growth is derived from the **existing ledger** (affinity/stage, emotion
        events, active days) — zero LLM, zero new ingest. Group scopes, a
        disabled ``growth`` section and a set ``reset`` all yield the empty
        rollback shape (``growth=None``, zero drift). ``max_level`` and
        ``drift_cap`` bound the result; errors degrade instead of raising.
        """
        moment = self._clock()
        base = {
            "api_version": self.api_version,
            "umo": umo,
            "persona_id": None,
            "is_group": False,
            "isolated": False,
            "growth": None,
            "drift": {"warmth_delta": 0.0, "verbosity_delta": 0.0},
            "degraded": False,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "degraded": True}
        if key.is_group:
            return {**base, "is_group": True, "isolated": True}
        cfg = self._growth_config()
        if not growth_available(cfg):
            if cfg.reset:
                try:
                    scope, _ = await self._private_scope(key, umo)
                    resolved = persona_id or self._resolve_persona(scope, legacy=key.user_id)
                    self._store.clear_growth_state(resolved, scope, now=moment)
                except Exception:
                    return {**base, "degraded": True}
            return base
        scope, _ = await self._private_scope(key, umo)
        resolved = persona_id or self._resolve_persona(scope, legacy=key.user_id)
        try:
            view = self._growth_for(scope, resolved, cfg, moment, persist=True)
        except Exception:
            return {**base, "persona_id": resolved, "degraded": True}
        return {
            **base,
            "persona_id": resolved,
            "growth": view["growth"],
            "drift": view["drift"],
        }

    # -- life line (v1.4) --------------------------------------------------
    async def get_life_line(self, umo: str, day: str | None = None) -> dict:
        """Return the structured life-line snapshot for ``umo`` on ``day``.

        Private scopes only: group scopes return an ``isolated`` empty snapshot
        (no weather/meal/sleep/diary), and a disabled ``life_line`` section
        returns the neutral default. Every dimension fails closed independently.
        """
        moment = self._clock()
        target_day = day or moment.date().isoformat()
        base = {
            "api_version": self.api_version,
            "umo": umo,
            "persona_id": None,
            "day": target_day,
            "weather": None,
            "meal": None,
            "sleep": None,
            "quiet": False,
            "diary": None,
            "isolated": False,
            "degraded": False,
        }
        try:
            key = parse_umo(umo)
        except Exception:
            return {**base, "degraded": True}
        if key.is_group:
            return {**base, "isolated": True, "persona_id": None}
        cfg = self._life_line_config()
        if not cfg.enabled:
            return base
        scope, _ = await self._private_scope(key, umo)
        resolved = self._resolve_persona(scope, legacy=key.user_id)
        try:
            detail = await self._life_detail(resolved, scope, moment, cfg, day=target_day)
        except Exception:
            return {**base, "persona_id": resolved, "degraded": True}
        return {
            **base,
            "persona_id": resolved,
            "weather": detail.get("weather"),
            "meal": detail.get("meal"),
            "sleep": detail.get("sleep"),
            "quiet": bool(detail.get("quiet")),
            "diary": detail.get("diary"),
        }

    async def get_diary(self, umo: str, day: str | None = None) -> dict | None:
        """Return the synthesized diary for ``umo`` on ``day`` (``None`` if any).

        Groups and a disabled section return ``None``. The row is synthesized
        once, deterministically and without an LLM, from that day's structured
        life line — never from raw message text.
        """
        try:
            key = parse_umo(umo)
        except Exception:
            return None
        if key.is_group:
            return None
        cfg = self._life_line_config()
        if not cfg.enabled:
            return None
        moment = self._clock()
        target_day = day or moment.date().isoformat()
        scope, _ = await self._private_scope(key, umo)
        resolved = self._resolve_persona(scope, legacy=key.user_id)
        try:
            return self._ensure_diary(resolved, scope, target_day, cfg)
        except Exception:
            return None

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

    # -- life line internals (v1.4) ----------------------------------------
    def _life_line_config(self) -> LifeLineConfig:
        """Parse the ``life_line`` group; defaults on any failure.

        Re-parsed on every call so AstrBot hot-reload is honoured immediately.
        """
        try:
            return parse_life_line_config(self._config)
        except Exception:
            return LifeLineConfig()

    # -- group / growth internals (v1.6) -----------------------------------
    def _group_config(self) -> GroupConfig:
        """Parse the ``group`` group; defaults on any failure (hot-reload safe)."""
        try:
            return parse_group_config(self._config)
        except Exception:
            return GroupConfig()

    def _growth_config(self) -> GrowthConfig:
        """Parse the ``growth`` group; defaults on any failure (hot-reload safe)."""
        try:
            return parse_growth_config(self._config)
        except Exception:
            return GrowthConfig()

    def _group_context(
        self, umo: str, moment: datetime, *, member_id: str | None = None, stamp: bool = False
    ) -> dict | None:
        """Derive the group context (``None`` when the section is disabled).

        When ``stamp`` is true and the gate allows participation, the advisory
        slot is consumed (cooldown/hourly windows advance). Reads no private
        state and writes only bounded group aggregates.
        """
        cfg = self._group_config()
        if not cfg.enabled:
            return None
        key = parse_umo(umo)
        hour_key = moment.strftime("%Y-%m-%dT%H")
        row = self._store.get_group_activity(umo) or {}
        hour_count = (
            int(row.get("hour_count") or 0) if row.get("hour_key") == hour_key else 0
        )
        part_count = (
            int(row.get("part_hour_count") or 0)
            if row.get("part_hour_key") == hour_key
            else 0
        )
        participation = evaluate_participation(
            now=moment,
            cfg=cfg,
            last_participation_ts=row.get("last_participation_ts"),
            participation_hour_count=part_count,
            activity_hour_count=hour_count,
        )
        if stamp and participation["allow"]:
            self._store.stamp_group_participation(umo, now=moment)
            participation = {
                **participation,
                "hourly_remaining": max(0, cfg.hourly_limit - (part_count + 1)),
            }
        member_key = (
            member_key_for(key.user_id, member_id)
            if cfg.member_tracking_enabled
            else ""
        )
        member_row = self._store.get_group_member(umo, member_key) if member_key else None
        return {
            "api_version": self.api_version,
            "umo": umo,
            "persona_id": None,
            "is_group": True,
            "isolated": False,
            "group": {
                "member_count": (
                    self._store.count_group_members(umo)
                    if cfg.member_tracking_enabled
                    else 0
                ),
                "activity_level": activity_level(hour_count, cfg.busy_group_threshold),
                "topic": str(row.get("topic") or ""),
                "topic_age_min": topic_age_min(row.get("topic_ts"), moment),
                "last_activity": str(row.get("last_activity_ts") or ""),
            },
            "participation": participation,
            "member": {
                "member_key": member_key,
                "familiarity": int((member_row or {}).get("familiarity") or 0),
                "is_known": member_row is not None,
            },
            "degraded": False,
        }

    def _growth_for(
        self,
        scope: str,
        resolved: str,
        cfg: GrowthConfig,
        moment: datetime,
        *,
        persist: bool,
    ) -> dict:
        """Derive ``{growth, drift}`` from the existing ledger.

        ``persist`` writes the level/xp high-water mark (growth never regresses
        when affinity decays); it is off for the pure-read expression path.
        """
        state = self._store.resolve_relationship_state(scope)
        affinity = float(getattr(state, "affinity", 0.0) or 0.0) if state else 0.0
        stage = str(getattr(state, "stage", STAGE_STRANGER) or STAGE_STRANGER)
        active_days = self._store.count_active_days(resolved, scope)
        since = (moment - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
        events = self._store.list_emotion_events(resolved, scope, since_iso=since, limit=200)
        count = len(events)
        positive = sum(1 for event in events if float(event.get("delta") or 0.0) > 0)
        ratio = (positive / count) if count else 0.0

        max_level = max(0, int(cfg.max_level))
        xp_derived = derive_xp(affinity, active_days, max_level)
        level_derived, _ = derive_level(affinity, active_days, max_level)
        stored = self._store.get_growth_state(resolved, scope) or {}
        stored_level = min(max_level, max(0, int(stored.get("level") or 0)))
        stored_xp = max(0.0, float(stored.get("xp") or 0.0))
        level = min(max_level, max(level_derived, stored_level))
        xp = max(xp_derived, stored_xp)
        if persist and (level_derived > stored_level or xp_derived > stored_xp):
            self._store.upsert_growth_state(
                resolved, scope, level=level_derived, xp=xp_derived, now=moment
            )
        if max_level and level >= max_level:
            progress = 1.0
        else:
            progress = round(min(1.0, max(0.0, xp - level)), 4)
        return {
            "growth": {
                "level": level,
                "progress": progress,
                "max_level": max_level,
                "traits": derive_traits(
                    stage, active_days, ratio, event_count=count
                ),
            },
            "drift": derive_drift(level, max_level, cfg.drift_cap),
        }

    async def _nudge_warmth_with_growth(
        self, decision: dict, scope: str, resolved: str, moment: datetime
    ) -> dict:
        """Apply the bounded growth drift to ``style_hints.warmth`` (no mode change)."""
        cfg = self._growth_config()
        if not growth_available(cfg):
            return decision
        try:
            view = self._growth_for(scope, resolved, cfg, moment, persist=False)
        except Exception:
            return decision
        return with_growth_drift(decision, view["drift"]["warmth_delta"])

    def _weather_for(self, cfg: LifeLineConfig):
        """Return the effective weather client (injected wins, else lazy)."""
        if self._injected_weather is not None:
            return self._injected_weather
        key = (cfg.weather_api_base, cfg.weather_timeout_sec, cfg.weather_ttl_min)
        if self._weather_client is None or self._weather_key != key:
            self._weather_client = WeatherClient(
                api_base=cfg.weather_api_base,
                timeout=cfg.weather_timeout_sec,
                ttl_minutes=cfg.weather_ttl_min,
            )
            self._weather_key = key
        return self._weather_client

    async def _life_detail(
        self, persona_id: str, user_id: str, moment: datetime, cfg: LifeLineConfig, *, day=None
    ) -> dict:
        """Assemble the private life detail (weather/meal/sleep/quiet/diary)."""
        target_day = day or moment.date().isoformat()
        minute = moment.hour * 60 + moment.minute
        detail: dict = {
            "weather": None,
            "meal": None,
            "sleep": None,
            "quiet": False,
            "diary": None,
        }

        if cfg.city:
            try:
                detail["weather"] = await self._weather_for(cfg).get(cfg.city)
            except Exception:
                detail["weather"] = None

        if cfg.meal_reminders_enabled:
            meal = meal_view(minute, cfg.meal_windows())
            detail["meal"] = meal
            if meal and meal.get("in_window"):
                try:
                    self._store.insert_life_event(
                        persona_id,
                        user_id,
                        kind="meal",
                        dedupe_key=f"meal:{meal['slot']}:{target_day}",
                        payload={"slot": meal["slot"], "day": target_day},
                        ts=moment,
                    )
                except Exception:
                    pass

        sleep_view = self._resolve_sleep_window(persona_id, user_id, target_day, moment, cfg)
        detail["sleep"] = sleep_view
        detail["quiet"] = self._quiet_now(cfg, sleep_view, moment, persona_id, user_id)
        try:
            detail["diary"] = self._previous_diary(persona_id, user_id, target_day, cfg)
        except Exception:
            detail["diary"] = None
        return detail

    def _resolve_sleep_window(
        self,
        persona_id: str,
        user_id: str,
        day: str,
        moment: datetime,
        cfg: LifeLineConfig,
    ) -> dict | None:
        """Return ``{window,since,source}`` for the day (auto) or ``None``."""
        if not cfg.sleep_window_auto:
            return None
        try:
            row = self._store.get_sleep_window(persona_id, user_id, day)
        except Exception:
            row = None
        if row is None:
            since = (moment - timedelta(days=SLEEP_INFER_DAYS)).isoformat()
            try:
                stamps = self._store.list_activity_timestamps(
                    persona_id, user_id, since_iso=since
                )
            except Exception:
                stamps = []
            start, end, source = infer_sleep_window(stamps)
            try:
                row = self._store.upsert_sleep_window(
                    persona_id, user_id, day, start_min=start, end_min=end, source=source
                )
            except Exception:
                row = {"start_min": start, "end_min": end, "source": source}
        if not row:
            return None
        start_min = int(row.get("start_min") or 0)
        end_min = int(row.get("end_min") or 0)
        minute = moment.hour * 60 + moment.minute
        inside = day == moment.date().isoformat() and in_window(
            minute, (start_min, end_min)
        )
        return {
            "window": f"{format_minutes(start_min)}-{format_minutes(end_min)}",
            "since": format_minutes(start_min) if inside else "",
            "source": str(row.get("source") or "default"),
            "start_min": start_min,
            "end_min": end_min,
        }

    def _quiet_now(
        self,
        cfg: LifeLineConfig,
        sleep_view: dict | None,
        moment: datetime,
        persona_id: str,
        user_id: str,
    ) -> bool:
        """Effective quiet-hours flag for a private scope (D3).

        Uses the inferred sleep window when ``sleep_window_auto`` is on, else the
        configured ``quiet_hours``. ``proactive_opt_in`` or a user interaction in
        the last :data:`QUIET_INTERACTION_GRACE_MIN` minutes exempts suppression.
        """
        if cfg.sleep_window_auto and sleep_view is not None:
            window = (sleep_view["start_min"], sleep_view["end_min"])
        else:
            window = cfg.quiet_window()
        if window is None:
            return False
        minute = moment.hour * 60 + moment.minute
        if not in_window(minute, window):
            return False
        if cfg.proactive_opt_in:
            return False
        try:
            last = self._store.get_interaction_dynamics(persona_id, user_id).last_interaction_at
        except Exception:
            last = None
        parsed = _parse_iso(last)
        if parsed is not None:
            gap = (moment - parsed).total_seconds()
            if 0 <= gap <= QUIET_INTERACTION_GRACE_MIN * 60:
                return False
        return True

    def _previous_diary(
        self, persona_id: str, user_id: str, day: str, cfg: LifeLineConfig
    ) -> dict | None:
        """Ensure and return the diary for the day before ``day``."""
        try:
            base = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        except ValueError:
            return None
        previous = (base - timedelta(days=1)).date().isoformat()
        return self._ensure_diary(persona_id, user_id, previous, cfg)

    def _ensure_diary(
        self, persona_id: str, user_id: str, day: str, cfg: LifeLineConfig
    ) -> dict | None:
        """Deterministically synthesize ``day``'s diary once (``INSERT OR IGNORE``)."""
        try:
            row = self._store.get_diary(persona_id, user_id, day)
        except Exception:
            return None
        if row is not None:
            return row
        try:
            base = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        except ValueError:
            return None
        until = (base + timedelta(days=1)).isoformat()
        sleep_window = None
        try:
            sleep_row = self._store.get_sleep_window(persona_id, user_id, day)
            if sleep_row is not None:
                sleep_window = (int(sleep_row["start_min"]), int(sleep_row["end_min"]))
        except Exception:
            sleep_window = None
        meals: set[str] = set()
        try:
            for event in self._store.list_life_events(persona_id, user_id, day=day, kind="meal"):
                parts = str(event.get("dedupe_key") or "").split(":")
                if len(parts) >= 2 and parts[1]:
                    meals.add(parts[1])
        except Exception:
            meals = set()
        try:
            life = self._store.get_life_state(persona_id, day) or {}
        except Exception:
            life = {}
        activity = str(life.get("activity") or "")
        try:
            events = self._store.list_emotion_events(
                persona_id, user_id, since_iso=f"{day}T00:00:00", until_iso=until, limit=200
            )
            mood = emotion_state(events, now=base + timedelta(days=1))
        except Exception:
            mood = STATE_CALM
        diary = synthesize_diary(
            day,
            sleep_window=sleep_window,
            meals=sorted(meals),
            activity=activity,
            mood=mood,
        )
        try:
            self._store.insert_diary(
                persona_id, user_id, day, summary=diary["summary"], mood=diary["mood"]
            )
            return self._store.get_diary(persona_id, user_id, day)
        except Exception:
            return diary

    # -- memory bridge (v1.3) ----------------------------------------------
    def _memory_query(
        self,
        moment: datetime,
        life_state: dict | None,
        stage: str,
        open_threads: list[str],
        is_group: bool,
    ) -> str:
        """Derive a short, zero-LLM query for the memory plugin.

        Joins the current life activity/scene, the two freshest open-thread
        labels and the relationship stage; when all of those are empty it
        degrades to ``<time window> <session type>``. Always clipped to
        :data:`memory_bridge.QUERY_MAX_CHARS`.
        """
        life = life_state or {}
        parts = [
            str(life.get("activity") or ""),
            str(life.get("scene") or ""),
            *[str(label) for label in list(open_threads)[:2]],
            str(stage or ""),
        ]
        query = " ".join(part for part in parts if part).strip()
        if not query:
            _, window_label = time_window(moment.hour)
            query = f"{window_label}{'群聊' if is_group else '私聊'}"
        return query[:100]

    async def _memory_payload(
        self,
        umo: str,
        *,
        is_group: bool,
        moment: datetime,
        life_state: dict | None,
        stage: str,
        open_threads: list[str],
    ) -> dict | None:
        """Read the optional memory payload; ``None`` on any failure.

        Fail-closed: no bridge, plugin missing, timeout, error or simply no
        memory data all return ``None``, so ``get_proactive_context`` emits no
        ``memory`` key and stays byte-identical to v1.2.0.
        """
        bridge = self._memory_bridge
        if bridge is None:
            return None
        try:
            query = self._memory_query(moment, life_state, stage, open_threads, is_group)
            payload = await bridge.fetch(
                umo,
                query=query,
                session_type="group" if is_group else "private",
            )
        except Exception:
            return None
        if not isinstance(payload, dict) or not payload:
            return None
        return payload

    @staticmethod
    def _memory_hints(memory: dict | None) -> tuple[str, ...]:
        """Derive label-matching hints (profile facets + highlights) for fusion."""
        if not isinstance(memory, dict):
            return ()
        profile = memory.get("profile")
        if not isinstance(profile, dict):
            return ()
        hints: list[str] = []
        facets = profile.get("facets")
        if isinstance(facets, dict):
            hints.extend(str(key) for key in facets if str(key or "").strip())
        highlights = profile.get("highlights")
        if isinstance(highlights, (list, tuple)):
            hints.extend(str(item) for item in highlights if str(item or "").strip())
        return tuple(hints)

    async def _nudge_warmth_with_memory(self, decision: dict, umo: str) -> dict:
        """Raise ``style_hints.warmth`` by at most +0.05 when a profile exists.

        Never changes ``mode`` and never lowers warmth; without a profile the
        ``decision`` is returned untouched (private scopes only).
        """
        bridge = self._memory_bridge
        if bridge is None:
            return decision
        try:
            payload = await bridge.fetch(umo, query="", session_type="private")
        except Exception:
            return decision
        if not isinstance(payload, dict) or not payload.get("profile"):
            return decision
        hints = dict(decision.get("style_hints") or {})
        try:
            base = float(hints.get("warmth") or 0.0)
        except (TypeError, ValueError):
            base = 0.0
        hints["warmth"] = round(min(base + MEMORY_WARMTH_MAX_DELTA, base + MEMORY_WARMTH_STEP), 4)
        return {**decision, "style_hints": hints}

    async def _private_scope(self, key, umo: str) -> tuple[str, str]:
        """Resolve ``(scope_key, person_id)`` for a private scope (v1.5).

        The scope key is what the store is keyed by: the authoritative
        ``person_id`` from the memory bridge when it resolves one, else the
        ``parse_umo().user_id`` fallback (v1.4.0 behaviour). Fail-closed: any
        bridge error/absence simply yields the fallback key, and ``person_id``
        is ``""``. Group scopes must not call this (they keep ``group:<session>``).
        """
        person_id = ""
        bridge = self._memory_bridge
        if bridge is not None:
            try:
                person_id = await bridge.resolve_person(umo) or ""
            except Exception:
                person_id = ""
        return (person_id or key.user_id), person_id

    def _resolve_persona(self, scope: str, legacy: str = "") -> str:
        """Resolve the persona owning ``scope`` (falls back to default).

        ``legacy`` is the pre-v1.5 (``parse_umo``) key, tried second so a row
        that predates the identity migration is still found.
        """
        for candidate in (scope, legacy):
            if not candidate:
                continue
            try:
                state = self._store.resolve_relationship_state(candidate)
            except Exception:
                continue
            if state is not None and state.persona_id:
                return state.persona_id
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
