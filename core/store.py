"""Thin SQLite-backed store for the Phase 1 contract.

The store only reads/writes derived values — never message bodies.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import db as schema
from .emotion import apply_emotion_affinity_delta, cap_emotion_delta
from .life_state import WeeklySchedule
from .motivation import (
    DEFAULT_OPEN_THREAD_LIMIT,
    OPEN_THREAD_EXPIRE_DAYS,
    OPEN_THREAD_MAX,
    OPEN_THREAD_TTL_DAYS,
    sanitize_thread_title,
)
from .relationship import (
    DAILY_DECAY,
    InteractionDynamics,
    RelationshipState,
    clamp_affinity,
    derive_bond,
    effective_delta,
    stage_for,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _stats_values(row) -> dict:
    if row is None:
        return {
            "message_count": 0,
            "proactive_sent": 0,
            "proactive_replied": 0,
            "unanswered_streak": 0,
            "reply_delay_sum": 0.0,
            "reply_delay_count": 0,
            "pending_proactive_at": None,
            "last_interaction_at": None,
        }
    return {
        "message_count": int(row["message_count"] or 0),
        "proactive_sent": int(row["proactive_sent"] or 0),
        "proactive_replied": int(row["proactive_replied"] or 0),
        "unanswered_streak": int(row["unanswered_streak"] or 0),
        "reply_delay_sum": float(row["reply_delay_sum"] or 0.0),
        "reply_delay_count": int(row["reply_delay_count"] or 0),
        "pending_proactive_at": row["pending_proactive_at"],
        "last_interaction_at": row["last_interaction_at"],
    }


class Store:
    """Owns the SQLite connection and schema lifecycle."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def open(cls, db_path: str | Path | None = None) -> Store:
        """Open (creating if needed) the plugin database and run migrations."""
        if db_path is None:
            from .paths import get_db_path

            db_path = get_db_path()
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = schema.connect(str(db_path) if db_path != ":memory:" else None)
        schema.apply_migrations(conn)
        return cls(conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def schema_version(self) -> int:
        with self._lock:
            return schema.get_schema_version(self._conn)

    def migrate(self) -> int:
        """Run pending migrations again (idempotent). Returns the version."""
        with self._lock:
            return schema.apply_migrations(self._conn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- personas ----------------------------------------------------------
    def upsert_persona(self, persona_id: str, display_name: str = "") -> None:
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO personas (persona_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(persona_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (persona_id, display_name, now, now),
            )
            self._conn.commit()

    def get_persona(self, persona_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM personas WHERE persona_id = ?", (persona_id,)
            ).fetchone()
        return dict(row) if row else None

    # -- life state --------------------------------------------------------
    def upsert_life_state(self, state) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO life_state_daily
                    (persona_id, day, activity, energy, scene, summary, as_of)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(persona_id, day) DO UPDATE SET
                    activity = excluded.activity,
                    energy = excluded.energy,
                    scene = excluded.scene,
                    summary = excluded.summary,
                    as_of = excluded.as_of
                """,
                (
                    state.persona_id,
                    state.as_of[:10],
                    state.activity,
                    state.energy,
                    state.scene,
                    state.summary,
                    state.as_of,
                ),
            )
            self._conn.commit()

    def get_life_state(self, persona_id: str, day: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM life_state_daily WHERE persona_id = ? AND day = ?",
                (persona_id, day),
            ).fetchone()
        return dict(row) if row else None

    def list_life_states(self, day: str) -> list[dict]:
        """Return all life_state_daily rows for a given day."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM life_state_daily WHERE day = ? ORDER BY persona_id",
                (day,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- schedule ----------------------------------------------------------
    def replace_schedule(self, schedule: WeeklySchedule) -> None:
        """Replace a persona's weekly template atomically."""
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                "DELETE FROM life_schedule WHERE persona_id = ?",
                (schedule.persona_id,),
            )
            self._conn.executemany(
                """
                INSERT INTO life_schedule
                    (schedule_id, persona_id, weekday, start_min, end_min,
                     activity, scene, energy, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{schedule.persona_id}:{i}",
                        schedule.persona_id,
                        event.weekday,
                        event.start_min,
                        event.end_min,
                        event.activity,
                        event.scene,
                        event.energy,
                        now,
                    )
                    for i, event in enumerate(schedule.events)
                ],
            )
            self._conn.commit()

    def load_schedule(self, persona_id: str) -> WeeklySchedule | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM life_schedule WHERE persona_id = ? ORDER BY weekday, start_min",
                (persona_id,),
            ).fetchall()
        if not rows:
            return None
        return WeeklySchedule.from_rows(persona_id, rows)

    # -- relationships -----------------------------------------------------
    def get_relationship_state(self, persona_id: str, user_id: str) -> RelationshipState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM relationships WHERE persona_id = ? AND user_id = ?",
                (persona_id, user_id),
            ).fetchone()
        return RelationshipState.from_row(row) if row else None

    def resolve_relationship_state(
        self, user_id: str, persona_id: str | None = None
    ) -> RelationshipState | None:
        """Return one relationship row; latest-updated when persona is omitted."""
        sql = "SELECT * FROM relationships WHERE user_id = ?"
        params: list = [user_id]
        if persona_id is not None:
            sql += " AND persona_id = ?"
            params.append(persona_id)
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return RelationshipState.from_row(row) if row else None

    def save_relationship_state(self, state: RelationshipState) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO relationships
                    (persona_id, user_id, affinity, stage, bond,
                     last_active_day, last_decay_day, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(persona_id, user_id) DO UPDATE SET
                    affinity = excluded.affinity,
                    stage = excluded.stage,
                    bond = excluded.bond,
                    last_active_day = excluded.last_active_day,
                    last_decay_day = excluded.last_decay_day,
                    updated_at = excluded.updated_at
                """,
                (
                    state.persona_id,
                    state.user_id,
                    clamp_affinity(state.affinity),
                    state.stage,
                    1 if state.bond else 0,
                    state.last_active_day,
                    state.last_decay_day,
                    state.updated_at or _utcnow_iso(),
                ),
            )
            self._conn.commit()

    # -- affinity ledger (append-only; dedup: persona+user+event) ----------
    def ledger_has_event(self, persona_id: str, user_id: str, event_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM affinity_ledger "
                "WHERE persona_id = ? AND user_id = ? AND event_id = ?",
                (persona_id, user_id, event_id),
            ).fetchone()
        return row is not None

    def ledger_daily_positive(self, persona_id: str, user_id: str, day: str) -> float:
        """Sum of positive deltas already booked for ``(persona, user, day)``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(delta), 0) AS total FROM affinity_ledger
                WHERE persona_id = ? AND user_id = ? AND day = ? AND delta > 0
                """,
                (persona_id, user_id, day),
            ).fetchone()
        return float(row["total"] or 0.0)

    def ledger_daily_negative(self, persona_id: str, user_id: str, day: str) -> float:
        """Sum of |negative deltas| already booked for ``(persona, user, day)``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(-delta), 0) AS total FROM affinity_ledger
                WHERE persona_id = ? AND user_id = ? AND day = ? AND delta < 0
                """,
                (persona_id, user_id, day),
            ).fetchone()
        return float(row["total"] or 0.0)

    def list_affinity_ledger(self, persona_id: str, user_id: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM affinity_ledger
                WHERE persona_id = ? AND user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (persona_id, user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def apply_affinity_event(
        self,
        persona_id: str,
        user_id: str,
        event_id: str,
        delta: float,
        reason: str = "",
        now: datetime | None = None,
        *,
        bond_event: bool = False,
    ) -> dict:
        """Book one affinity event under the anti-inflation rules.

        Idempotent per ``(persona_id, user_id, event_id)``; positive gain is
        clamped to the single-event cap and the remaining daily allowance.
        Returns ``{"applied", "duplicate", "delta", "state"}``.
        """
        moment = now or _utcnow()
        day = moment.date().isoformat()
        with self._lock:
            if self.ledger_has_event(persona_id, user_id, event_id):
                return {
                    "applied": False,
                    "duplicate": True,
                    "delta": 0.0,
                    "state": self.get_relationship_state(persona_id, user_id),
                }
            used = self.ledger_daily_positive(persona_id, user_id, day)
            applied = effective_delta(delta, used)
            current = self.get_relationship_state(persona_id, user_id) or RelationshipState(
                persona_id=persona_id, user_id=user_id, updated_at=moment.isoformat()
            )
            if applied <= 0:
                return {"applied": False, "duplicate": False, "delta": 0.0, "state": current}
            affinity = clamp_affinity(current.affinity + applied)
            stage = stage_for(affinity, current.stage)
            bond = derive_bond(stage, bond_event, current.bond)
            self._conn.execute(
                """
                INSERT INTO affinity_ledger
                    (persona_id, user_id, event_id, delta, reason, day, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (persona_id, user_id, event_id, applied, reason, day, moment.isoformat()),
            )
            state = RelationshipState(
                persona_id=persona_id,
                user_id=user_id,
                affinity=affinity,
                stage=stage,
                bond=bond,
                last_active_day=day,
                last_decay_day=current.last_decay_day,
                updated_at=moment.isoformat(),
            )
            self._conn.commit()
        self.save_relationship_state(state)
        return {"applied": True, "duplicate": False, "delta": applied, "state": state}

    def apply_decay(
        self, persona_id: str, user_id: str, now: datetime | None = None
    ) -> RelationshipState | None:
        """Apply idle-day decay (-0.005/day toward 0). Idempotent per day."""
        moment = now or _utcnow()
        today = moment.date()
        state = self.get_relationship_state(persona_id, user_id)
        if state is None:
            return None
        candidates = [
            parsed
            for parsed in (_parse_day(state.last_decay_day), _parse_day(state.last_active_day))
            if parsed is not None
        ]
        reference = max(candidates) if candidates else (_parse_day(state.updated_at) or today)
        days = (today - reference).days
        if days <= 0:
            return state
        affinity = clamp_affinity(state.affinity - DAILY_DECAY * days)
        stage = stage_for(affinity, state.stage)
        state = RelationshipState(
            persona_id=state.persona_id,
            user_id=state.user_id,
            affinity=affinity,
            stage=stage,
            bond=derive_bond(stage, False, state.bond),
            last_active_day=state.last_active_day,
            last_decay_day=today.isoformat(),
            updated_at=moment.isoformat(),
        )
        self.save_relationship_state(state)
        return state

    # -- emotion-event ledger (append-only; dedup: persona+user+key) --------
    def emotion_event_exists(self, persona_id: str, user_id: str, dedupe_key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM emotion_events "
                "WHERE persona_id = ? AND user_id = ? AND dedupe_key = ?",
                (persona_id, user_id, dedupe_key),
            ).fetchone()
        return row is not None

    def list_emotion_events(
        self,
        persona_id: str,
        user_id: str,
        *,
        since_iso: str | None = None,
        until_iso: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return recent emotion events (derived values only, no message text)."""
        sql = "SELECT * FROM emotion_events WHERE persona_id = ? AND user_id = ?"
        params: list = [persona_id, user_id]
        if since_iso:
            sql += " AND ts >= ?"
            params.append(since_iso)
        if until_iso:
            sql += " AND ts < ?"
            params.append(until_iso)
        sql += " ORDER BY ts DESC, dedupe_key DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def apply_emotion_event(
        self,
        persona_id: str,
        user_id: str,
        *,
        event_id: str,
        event_type: str,
        delta: float,
        reason: str = "",
        now: datetime | None = None,
    ) -> dict:
        """Record one emotion event (idempotent per ``(persona, user, event_id)``).

        The stored event keeps the canonical per-event delta so the valence
        model sees the full signal; the affinity ledger receives the *capped*
        delta (shared daily positive cap, negative cap, affinity floor ``0.0``).
        Returns ``{"applied", "duplicate", "delta", "event_delta", "state"}``.
        """
        moment = now or _utcnow()
        day = moment.date().isoformat()
        canonical = cap_emotion_delta(delta)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO emotion_events
                    (persona_id, user_id, dedupe_key, ts, event_type, delta, reason, day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persona_id,
                    user_id,
                    event_id,
                    moment.isoformat(),
                    event_type,
                    canonical,
                    reason,
                    day,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.commit()
                return {
                    "applied": False,
                    "duplicate": True,
                    "delta": 0.0,
                    "event_delta": canonical,
                    "state": self.get_relationship_state(persona_id, user_id),
                }
            current = self.get_relationship_state(persona_id, user_id) or RelationshipState(
                persona_id=persona_id, user_id=user_id, updated_at=moment.isoformat()
            )
            applied = apply_emotion_affinity_delta(
                canonical,
                daily_positive_used=self.ledger_daily_positive(persona_id, user_id, day),
                daily_negative_used=self.ledger_daily_negative(persona_id, user_id, day),
                affinity=current.affinity,
            )
            if applied == 0.0:
                self._conn.commit()
                return {
                    "applied": False,
                    "duplicate": False,
                    "delta": 0.0,
                    "event_delta": canonical,
                    "state": current,
                }
            affinity = clamp_affinity(current.affinity + applied)
            stage = stage_for(affinity, current.stage)
            bond = derive_bond(stage, False, current.bond)
            self._conn.execute(
                """
                INSERT INTO affinity_ledger
                    (persona_id, user_id, event_id, delta, reason, day, created_at, event_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persona_id,
                    user_id,
                    event_id,
                    applied,
                    reason,
                    day,
                    moment.isoformat(),
                    event_type,
                ),
            )
            state = RelationshipState(
                persona_id=persona_id,
                user_id=user_id,
                affinity=affinity,
                stage=stage,
                bond=bond,
                last_active_day=day,
                last_decay_day=current.last_decay_day,
                updated_at=moment.isoformat(),
            )
            self._conn.commit()
        self.save_relationship_state(state)
        return {
            "applied": True,
            "duplicate": False,
            "delta": applied,
            "event_delta": canonical,
            "state": state,
        }

    # -- interaction dynamics ---------------------------------------------
    def get_interaction_dynamics(self, persona_id: str, user_id: str) -> InteractionDynamics:
        with self._lock:
            row = self._read_stats_locked(persona_id, user_id)
        return InteractionDynamics.from_row(row)

    def record_user_message(
        self,
        persona_id: str,
        user_id: str,
        now: datetime | None = None,
        count: int = 1,
    ) -> InteractionDynamics:
        """Observe an inbound user message; clears a pending proactive wait."""
        moment = now or _utcnow()
        with self._lock:
            values = _stats_values(self._read_stats_locked(persona_id, user_id))
            values["message_count"] += count
            values["last_interaction_at"] = moment.isoformat()
            pending = values["pending_proactive_at"]
            if pending:
                delay = (moment - datetime.fromisoformat(pending)).total_seconds()
                if delay >= 0:
                    values["reply_delay_sum"] += delay
                    values["reply_delay_count"] += 1
                values["unanswered_streak"] = 0
                values["pending_proactive_at"] = None
            self._write_stats_locked(persona_id, user_id, values, moment)
        return self.get_interaction_dynamics(persona_id, user_id)

    def record_proactive_outcome(
        self,
        persona_id: str,
        user_id: str,
        *,
        sent: bool,
        replied: bool = False,
        now: datetime | None = None,
    ) -> InteractionDynamics:
        """Record a proactive-send outcome; unanswered sends grow the streak."""
        moment = now or _utcnow()
        with self._lock:
            values = _stats_values(self._read_stats_locked(persona_id, user_id))
            if sent:
                values["proactive_sent"] += 1
                if replied:
                    values["proactive_replied"] += 1
                    values["unanswered_streak"] = 0
                    values["pending_proactive_at"] = None
                else:
                    values["unanswered_streak"] += 1
                    values["pending_proactive_at"] = moment.isoformat()
            self._write_stats_locked(persona_id, user_id, values, moment)
        return self.get_interaction_dynamics(persona_id, user_id)

    def _read_stats_locked(self, persona_id: str, user_id: str):
        return self._conn.execute(
            "SELECT * FROM interaction_stats WHERE persona_id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()

    def _write_stats_locked(
        self, persona_id: str, user_id: str, values: dict, now: datetime
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO interaction_stats
                (persona_id, user_id, message_count, proactive_sent, proactive_replied,
                 unanswered_streak, reply_delay_sum, reply_delay_count,
                 pending_proactive_at, last_interaction_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(persona_id, user_id) DO UPDATE SET
                message_count = excluded.message_count,
                proactive_sent = excluded.proactive_sent,
                proactive_replied = excluded.proactive_replied,
                unanswered_streak = excluded.unanswered_streak,
                reply_delay_sum = excluded.reply_delay_sum,
                reply_delay_count = excluded.reply_delay_count,
                pending_proactive_at = excluded.pending_proactive_at,
                last_interaction_at = excluded.last_interaction_at,
                updated_at = excluded.updated_at
            """,
            (
                persona_id,
                user_id,
                values["message_count"],
                values["proactive_sent"],
                values["proactive_replied"],
                values["unanswered_streak"],
                values["reply_delay_sum"],
                values["reply_delay_count"],
                values["pending_proactive_at"],
                values["last_interaction_at"],
                now.isoformat(),
            ),
        )
        self._conn.commit()

    # -- open threads (short labels only) ----------------------------------
    def upsert_open_thread(
        self,
        thread_id: str,
        umo: str,
        persona_id: str,
        title: str,
        *,
        status: str = "open",
        kind: str = "topic",
        source: str = "",
        confidence: float = 0.0,
        dedupe_key: str | None = None,
        closed_reason: str = "",
        now: datetime | None = None,
    ) -> dict:
        """Insert/update an open-thread row. Title is reduced to a short label.

        Idempotent by ``thread_id``: a repeat mention refreshes
        ``title/status/last_seen_ts/updated_at`` and never inserts a second row
        (nor resets the follow-up counters).
        """
        moment = now or _utcnow()
        label = sanitize_thread_title(title)
        stamp = moment.isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO open_threads
                    (thread_id, umo, persona_id, title, status, opened_at, updated_at,
                     kind, last_seen_ts, last_followup_ts, followup_count, source,
                     confidence, dedupe_key, closed_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    kind = excluded.kind,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    dedupe_key = excluded.dedupe_key,
                    closed_reason = excluded.closed_reason,
                    last_seen_ts = excluded.last_seen_ts,
                    updated_at = excluded.updated_at
                """,
                (
                    thread_id,
                    umo,
                    persona_id,
                    label,
                    status,
                    stamp,
                    stamp,
                    kind,
                    stamp,
                    source,
                    float(confidence or 0.0),
                    dedupe_key,
                    closed_reason,
                ),
            )
            self._conn.commit()
        return {
            "thread_id": thread_id,
            "umo": umo,
            "persona_id": persona_id,
            "title": label,
            "label": label,
            "status": status,
            "kind": kind,
            "source": source,
            "confidence": float(confidence or 0.0),
            "dedupe_key": dedupe_key,
            "closed_reason": closed_reason,
            "last_seen_ts": stamp,
            "updated_at": stamp,
        }

    def resolve_open_threads(
        self,
        umo: str,
        persona_id: str | None = None,
        limit: int = DEFAULT_OPEN_THREAD_LIMIT,
    ) -> list[dict]:
        """Return the most recently touched open threads for ``umo``."""
        sql = "SELECT * FROM open_threads WHERE umo = ? AND status = 'open'"
        params: list = [umo]
        if persona_id is not None:
            sql += " AND persona_id = ?"
            params.append(persona_id)
        sql += " ORDER BY updated_at DESC, thread_id LIMIT ?"
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_open_thread_details(
        self,
        umo: str,
        persona_id: str | None = None,
        status: str | Sequence[str] | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return open-thread rows (with lifecycle columns) for ``umo``.

        ``status`` accepts a single status or a sequence of them; ``None`` means
        every status. Ordered by ``last_seen_ts`` (newest first).
        """
        sql = "SELECT * FROM open_threads WHERE umo = ?"
        params: list = [umo]
        if persona_id is not None:
            sql += " AND persona_id = ?"
            params.append(persona_id)
        if status is not None:
            wanted = (status,) if isinstance(status, str) else tuple(status)
            if wanted:
                placeholders = ", ".join("?" for _ in wanted)
                sql += f" AND status IN ({placeholders})"
                params.extend(wanted)
        sql += " ORDER BY last_seen_ts DESC, updated_at DESC, thread_id LIMIT ?"
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def touch_open_thread(
        self,
        thread_id: str,
        *,
        umo: str | None = None,
        status: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Refresh a thread's ``last_seen_ts`` (and optionally ``status``)."""
        moment = now or _utcnow()
        assignments = ["last_seen_ts = ?", "updated_at = ?"]
        params: list = [moment.isoformat(), moment.isoformat()]
        if status is not None:
            assignments.insert(0, "status = ?")
            params.insert(0, status)
        sql = f"UPDATE open_threads SET {', '.join(assignments)} WHERE thread_id = ?"
        params.append(thread_id)
        if umo is not None:
            sql += " AND umo = ?"
            params.append(umo)
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
        return cursor.rowcount > 0

    def mark_thread_followup(
        self, thread_id: str, *, umo: str | None = None, now: datetime | None = None
    ) -> dict | None:
        """Record one proactive follow-up: bump the counter + stamp the time."""
        moment = now or _utcnow()
        sql = (
            "UPDATE open_threads SET followup_count = followup_count + 1, last_followup_ts = ? "
            "WHERE thread_id = ?"
        )
        params: list = [moment.isoformat(), thread_id]
        if umo is not None:
            sql += " AND umo = ?"
            params.append(umo)
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM open_threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return dict(row) if row else None

    def close_open_thread(
        self,
        thread_id: str,
        now: datetime | None = None,
        *,
        umo: str | None = None,
        reason: str = "",
    ) -> bool:
        """Mark a thread closed. Returns ``True`` when a row was updated."""
        moment = now or _utcnow()
        sql = (
            "UPDATE open_threads SET status = 'closed', closed_reason = ?, updated_at = ? "
            "WHERE thread_id = ?"
        )
        params: list = [reason, moment.isoformat(), thread_id]
        if umo is not None:
            sql += " AND umo = ?"
            params.append(umo)
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
        return cursor.rowcount > 0

    def expire_open_threads(
        self,
        now: datetime | None = None,
        *,
        ttl_days: int = OPEN_THREAD_TTL_DAYS,
        expire_days: int = OPEN_THREAD_EXPIRE_DAYS,
        max_open: int = OPEN_THREAD_MAX,
    ) -> dict:
        """Advance the open-thread lifecycle; returns per-stage counts.

        * hard expiry first: untouched for ``expire_days`` -> ``closed(expired)``;
        * TTL: untouched for ``ttl_days`` -> ``stale`` (kept, no longer a candidate);
        * LRU: per ``(umo, persona_id)`` keep the ``max_open`` newest ``open``
          rows and close the overflow with ``closed_reason='superseded'``.

        Idempotent for a given ``now``: already-stale/closed rows are not touched
        again by the earlier stages.
        """
        moment = now or _utcnow()
        stamp = moment.isoformat()
        ttl_cutoff = (moment - timedelta(days=max(0, int(ttl_days)))).isoformat()
        expire_cutoff = (moment - timedelta(days=max(0, int(expire_days)))).isoformat()
        with self._lock:
            expired = self._conn.execute(
                """
                UPDATE open_threads
                   SET status = 'closed', closed_reason = 'expired', updated_at = ?
                 WHERE status IN ('open', 'stale') AND last_seen_ts != ''
                   AND last_seen_ts < ?
                """,
                (stamp, expire_cutoff),
            ).rowcount
            stale = self._conn.execute(
                """
                UPDATE open_threads
                   SET status = 'stale', updated_at = ?
                 WHERE status = 'open' AND last_seen_ts != ''
                   AND last_seen_ts < ?
                """,
                (stamp, ttl_cutoff),
            ).rowcount
            evicted = 0
            if max_open >= 0:
                scopes = self._conn.execute(
                    """
                    SELECT umo, persona_id FROM open_threads
                     WHERE status = 'open'
                     GROUP BY umo, persona_id
                    HAVING COUNT(*) > ?
                    """,
                    (int(max_open),),
                ).fetchall()
                for scope in scopes:
                    overflow = self._conn.execute(
                        """
                        SELECT thread_id FROM open_threads
                         WHERE umo = ? AND persona_id = ? AND status = 'open'
                         ORDER BY last_seen_ts DESC, thread_id
                         LIMIT -1 OFFSET ?
                        """,
                        (scope["umo"], scope["persona_id"], int(max_open)),
                    ).fetchall()
                    for row in overflow:
                        cursor = self._conn.execute(
                            """
                            UPDATE open_threads
                               SET status = 'closed', closed_reason = 'superseded',
                                   updated_at = ?
                             WHERE thread_id = ?
                            """,
                            (stamp, row["thread_id"]),
                        )
                        evicted += cursor.rowcount
            self._conn.commit()
        return {"stale": stale, "expired": expired, "evicted": evicted}

    def list_open_threads(self, status: str | None = None, limit: int = 200) -> list[dict]:
        """Return open-thread rows for the read-only panel."""
        sql = "SELECT * FROM open_threads"
        params: list = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # -- motivation audit log ----------------------------------------------
    def motivation_receipt_exists(self, persona_id: str, user_id: str, receipt_key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM motivation_log "
                "WHERE persona_id = ? AND user_id = ? AND receipt_key = ?",
                (persona_id, user_id, receipt_key),
            ).fetchone()
        return row is not None

    def log_motivation(
        self,
        *,
        persona_id: str,
        umo: str = "",
        user_id: str = "",
        kind: str = "motivation",
        score: float = 0.0,
        reason: str = "",
        candidates: Sequence[dict] | None = None,
        selected_reason: str = "",
        adopted: bool = False,
        blocked_reason: str = "",
        reason_code: str = "",
        receipt_key: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Append one audit row. Idempotent when ``receipt_key`` is supplied.

        Returns ``{"written", "duplicate", "entry_id"}``. Only derived values
        (scores, short reasons, candidate tags) are persisted — never message
        bodies.
        """
        moment = now or _utcnow()
        with self._lock:
            if receipt_key is not None and self.motivation_receipt_exists(
                persona_id, user_id, receipt_key
            ):
                return {"written": False, "duplicate": True, "entry_id": None}
            entry_id = uuid.uuid4().hex
            self._conn.execute(
                """
                INSERT INTO motivation_log
                    (entry_id, persona_id, kind, value, reason, created_at, umo, user_id,
                     candidates_json, selected_reason, adopted, blocked_reason,
                     reason_code, receipt_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    persona_id,
                    kind,
                    float(score),
                    reason,
                    moment.isoformat(),
                    umo,
                    user_id,
                    json.dumps(list(candidates or []), ensure_ascii=False),
                    selected_reason,
                    1 if adopted else 0,
                    blocked_reason,
                    reason_code,
                    receipt_key,
                ),
            )
            self._conn.commit()
        return {"written": True, "duplicate": False, "entry_id": entry_id}

    def count_proactive_sent(self, persona_id: str, user_id: str, since_iso: str) -> int:
        """Count adopted proactive sends for a scope since ``since_iso``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS total FROM motivation_log
                WHERE persona_id = ? AND user_id = ? AND kind = 'proactive_outcome'
                  AND adopted = 1 AND created_at >= ?
                """,
                (persona_id, user_id, since_iso),
            ).fetchone()
        return int(row["total"] or 0)

    # -- list queries (read-only panel) ------------------------------------
    def list_relationships(self, persona_id: str | None = None) -> list[dict]:
        """Return all relationships, optionally filtered by persona_id."""
        sql = "SELECT * FROM relationships"
        params: list = []
        if persona_id is not None:
            sql += " WHERE persona_id = ?"
            params.append(persona_id)
        sql += " ORDER BY affinity DESC, updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_motivation_log(self, persona_id: str | None = None, limit: int = 50) -> list[dict]:
        """Return recent motivation_log entries, optionally filtered by persona_id."""
        sql = "SELECT * FROM motivation_log"
        params: list = []
        if persona_id is not None:
            sql += " WHERE persona_id = ?"
            params.append(persona_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # -- life line (v1.4, schema v6) ---------------------------------------
    def insert_life_event(
        self,
        persona_id: str,
        user_id: str,
        *,
        kind: str,
        dedupe_key: str,
        payload: dict | None = None,
        ts: datetime | None = None,
    ) -> bool:
        """Record one structured life event; idempotent per ``dedupe_key``.

        ``INSERT OR IGNORE`` on ``UNIQUE(persona_id, user_id, dedupe_key)`` so a
        repeated read never duplicates an event. Returns ``True`` when a row was
        inserted. Only derived values are stored (codes, windows) — no raw text.
        """
        moment = ts or _utcnow()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO life_events
                    (persona_id, user_id, ts, kind, payload_json, dedupe_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    persona_id,
                    user_id,
                    moment.isoformat(),
                    kind,
                    json.dumps(payload or {}, ensure_ascii=False),
                    dedupe_key,
                ),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def list_life_events(
        self,
        persona_id: str,
        user_id: str,
        *,
        day: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return structured life events for a scope, newest first."""
        sql = "SELECT * FROM life_events WHERE persona_id = ? AND user_id = ?"
        params: list = [persona_id, user_id]
        if day:
            sql += " AND ts >= ? AND ts < ?"
            params.extend([f"{day}T00:00:00", f"{day}T23:59:59.999999"])
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY ts DESC, dedupe_key DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_sleep_window(self, persona_id: str, user_id: str, day: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sleep_windows WHERE persona_id = ? AND user_id = ? AND day = ?",
                (persona_id, user_id, day),
            ).fetchone()
        return dict(row) if row else None

    def upsert_sleep_window(
        self,
        persona_id: str,
        user_id: str,
        day: str,
        *,
        start_min: int,
        end_min: int,
        source: str,
        overwrite: bool = False,
    ) -> dict:
        """Persist a day's inferred/default sleep window.

        Auto-inferred rows never clobber an existing row unless ``overwrite`` is
        set (manual wins). Returns the stored row.
        """
        start = max(0, min(1439, int(start_min)))
        end = max(0, min(1440, int(end_min)))
        with self._lock:
            if overwrite:
                self._conn.execute(
                    """
                    INSERT INTO sleep_windows
                        (persona_id, user_id, day, start_min, end_min, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(persona_id, user_id, day) DO UPDATE SET
                        start_min = excluded.start_min,
                        end_min = excluded.end_min,
                        source = excluded.source
                    """,
                    (persona_id, user_id, day, start, end, source),
                )
            else:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO sleep_windows
                        (persona_id, user_id, day, start_min, end_min, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (persona_id, user_id, day, start, end, source),
                )
            self._conn.commit()
        return self.get_sleep_window(persona_id, user_id, day)

    def list_activity_timestamps(
        self, persona_id: str, user_id: str, *, since_iso: str, limit: int = 2000
    ) -> list[str]:
        """Return recent interaction timestamps for a private scope.

        Zero-collection: reuses the emotion-event ledger timestamps plus the
        latest interaction stamp. No raw text is involved, only timestamps.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT ts FROM emotion_events
                 WHERE persona_id = ? AND user_id = ? AND ts >= ?
                 ORDER BY ts DESC LIMIT ?
                """,
                (persona_id, user_id, since_iso, max(0, int(limit))),
            ).fetchall()
            stats = self._conn.execute(
                "SELECT last_interaction_at FROM interaction_stats "
                "WHERE persona_id = ? AND user_id = ?",
                (persona_id, user_id),
            ).fetchone()
        stamps = [str(row["ts"]) for row in rows if row["ts"]]
        if stats is not None and stats["last_interaction_at"]:
            stamps.append(str(stats["last_interaction_at"]))
        return stamps

    def get_diary(self, persona_id: str, user_id: str, day: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM life_diary WHERE persona_id = ? AND user_id = ? AND day = ?",
                (persona_id, user_id, day),
            ).fetchone()
        return dict(row) if row else None

    def insert_diary(
        self, persona_id: str, user_id: str, day: str, *, summary: str, mood: str
    ) -> bool:
        """Insert a synthesized diary row once (``INSERT OR IGNORE``)."""
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO life_diary
                    (persona_id, user_id, day, summary, mood)
                VALUES (?, ?, ?, ?, ?)
                """,
                (persona_id, user_id, day, summary, mood),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    # -- helpers -----------------------------------------------------------
    def table_names(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {row[0] for row in rows}
