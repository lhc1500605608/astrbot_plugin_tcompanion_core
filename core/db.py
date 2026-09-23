"""SQLite schema definition and idempotent migration runner.

Invariants (see ``docs/CONTRACT.md``):
* No table stores raw message text. Only derived/aggregate values.
* ``apply_migrations`` is idempotent: re-running on an up-to-date database
  performs no writes and leaves ``schema_meta.schema_version`` unchanged.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

#: Current target schema version.
SCHEMA_VERSION = 7

#: A migration step is either a SQL script or a callable taking the connection
#: (needed when the DDL must be guarded by a runtime check, e.g. column
#: existence before ``ALTER TABLE``).
MigrationStep = str | Callable[["sqlite3.Connection"], None]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return whether ``table`` already has ``column`` (PRAGMA-based guard)."""
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """v4: emotion-event ledger + ``affinity_ledger.event_type`` (additive).

    Pure increment: existing rows are never rewritten, and the new column is
    added only when absent (``ADD COLUMN`` re-runs otherwise fail). Old code
    (v1.0.0) keeps working: it never queries ``emotion_events`` and inserts
    into ``affinity_ledger`` with an explicit column list, so the new column
    takes its default ``''``.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS emotion_events (
            persona_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            ts         TEXT NOT NULL,
            event_type TEXT NOT NULL,
            delta      REAL NOT NULL DEFAULT 0,
            reason     TEXT NOT NULL DEFAULT '',
            day        TEXT NOT NULL,
            PRIMARY KEY (persona_id, user_id, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_emotion_events_scope
            ON emotion_events (persona_id, user_id, ts);
        """
    )
    if not _column_exists(conn, "affinity_ledger", "event_type"):
        conn.execute(
            "ALTER TABLE affinity_ledger ADD COLUMN event_type TEXT NOT NULL DEFAULT ''"
        )


#: New ``open_threads`` columns added by v5 (name -> DDL tail after ``ADD COLUMN``).
V5_OPEN_THREAD_COLUMNS: dict[str, str] = {
    "kind": "kind TEXT NOT NULL DEFAULT 'topic'",
    "last_seen_ts": "last_seen_ts TEXT NOT NULL DEFAULT ''",
    "last_followup_ts": "last_followup_ts TEXT NOT NULL DEFAULT ''",
    "followup_count": "followup_count INTEGER NOT NULL DEFAULT 0",
    "source": "source TEXT NOT NULL DEFAULT ''",
    "confidence": "confidence REAL NOT NULL DEFAULT 0.0",
    "dedupe_key": "dedupe_key TEXT",
    "closed_reason": "closed_reason TEXT NOT NULL DEFAULT ''",
}


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """v5: open-thread lifecycle columns (additive).

    Pure increment: every ``ALTER TABLE`` is guarded by ``PRAGMA table_info``,
    so re-running is a no-op; **existing rows are never rewritten** except the
    one-time ``last_seen_ts = updated_at`` backfill (guarded to empty values).
    Old code (v1.1.x) keeps working: it inserts with an explicit column list, so
    the new columns take their defaults.
    """
    for column, ddl in V5_OPEN_THREAD_COLUMNS.items():
        if not _column_exists(conn, "open_threads", column):
            conn.execute(f"ALTER TABLE open_threads ADD COLUMN {ddl}")
    conn.execute(
        "UPDATE open_threads SET last_seen_ts = updated_at WHERE last_seen_ts = ''"
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_open_threads_lifecycle
            ON open_threads (umo, persona_id, status, last_seen_ts);
        CREATE INDEX IF NOT EXISTS idx_open_threads_dedupe
            ON open_threads (umo, persona_id, dedupe_key);
        """
    )


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """v6: life-line tables (additive).

    Pure increment: three new tables, created with ``CREATE TABLE IF NOT
    EXISTS`` and indexed separately, so re-running is a no-op and **no existing
    table or row is touched**. Old code (v1.3.x) never queries these tables and
    keeps working unchanged. Only structured fields are stored (time windows,
    event codes, a synthesized summary) — never raw message text.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sleep_windows (
            persona_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            day        TEXT NOT NULL,
            start_min  INTEGER NOT NULL,
            end_min    INTEGER NOT NULL,
            source     TEXT NOT NULL DEFAULT 'default',
            PRIMARY KEY (persona_id, user_id, day)
        );

        CREATE TABLE IF NOT EXISTS life_events (
            persona_id   TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            ts           TEXT NOT NULL,
            kind         TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            dedupe_key   TEXT NOT NULL,
            UNIQUE (persona_id, user_id, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_life_events_scope
            ON life_events (persona_id, user_id, kind, ts);

        CREATE TABLE IF NOT EXISTS life_diary (
            persona_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            day        TEXT NOT NULL,
            summary    TEXT NOT NULL DEFAULT '',
            mood       TEXT NOT NULL DEFAULT '',
            UNIQUE (persona_id, user_id, day)
        );
        """
    )


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """v7: group-understanding + growth tables (additive).

    Pure increment: three new tables created with ``CREATE TABLE IF NOT
    EXISTS`` (plus indexes), so re-running is a no-op and **no existing table or
    row is touched**. Old code (v1.5.x) never queries these tables and keeps
    working unchanged. Only bounded aggregates are stored (counts, timestamps,
    a sanitized short label) — **never raw message text**.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS group_activity (
            umo                 TEXT PRIMARY KEY,
            message_count       INTEGER NOT NULL DEFAULT 0,
            hour_key            TEXT NOT NULL DEFAULT '',
            hour_count          INTEGER NOT NULL DEFAULT 0,
            day                 TEXT NOT NULL DEFAULT '',
            day_count           INTEGER NOT NULL DEFAULT 0,
            topic               TEXT NOT NULL DEFAULT '',
            topic_ts            TEXT NOT NULL DEFAULT '',
            last_activity_ts    TEXT NOT NULL DEFAULT '',
            last_participation_ts TEXT NOT NULL DEFAULT '',
            part_hour_key       TEXT NOT NULL DEFAULT '',
            part_hour_count     INTEGER NOT NULL DEFAULT 0,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS group_members (
            umo          TEXT NOT NULL,
            member_key   TEXT NOT NULL,
            familiarity  INTEGER NOT NULL DEFAULT 0,
            msg_count    INTEGER NOT NULL DEFAULT 0,
            first_seen_ts TEXT NOT NULL DEFAULT '',
            last_seen_ts TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (umo, member_key)
        );
        CREATE INDEX IF NOT EXISTS idx_group_members_last_seen
            ON group_members (umo, last_seen_ts);

        CREATE TABLE IF NOT EXISTS growth_state (
            persona_id  TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            level       INTEGER NOT NULL DEFAULT 0,
            xp          REAL NOT NULL DEFAULT 0,
            reset_at    TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (persona_id, user_id)
        );
        """
    )


#: Ordered (version, step) pairs. Steps run at most once per database.
MIGRATIONS: tuple[tuple[int, MigrationStep], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS personas (
            persona_id   TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            meta_json    TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS life_state_daily (
            persona_id TEXT NOT NULL,
            day        TEXT NOT NULL,
            activity   TEXT NOT NULL DEFAULT '',
            energy     REAL NOT NULL DEFAULT 0,
            scene      TEXT NOT NULL DEFAULT '',
            summary    TEXT NOT NULL DEFAULT '',
            as_of      TEXT NOT NULL,
            PRIMARY KEY (persona_id, day)
        );

        CREATE TABLE IF NOT EXISTS life_schedule (
            schedule_id TEXT PRIMARY KEY,
            persona_id  TEXT NOT NULL,
            weekday     INTEGER NOT NULL,
            start_min   INTEGER NOT NULL,
            end_min     INTEGER NOT NULL,
            activity    TEXT NOT NULL,
            scene       TEXT NOT NULL DEFAULT '',
            energy      REAL NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_life_schedule_persona_weekday
            ON life_schedule (persona_id, weekday);

        CREATE TABLE IF NOT EXISTS relationships (
            umo        TEXT NOT NULL,
            persona_id TEXT NOT NULL,
            stage      TEXT NOT NULL DEFAULT 'stranger',
            closeness  REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (umo, persona_id)
        );

        CREATE TABLE IF NOT EXISTS affinity_ledger (
            entry_id   TEXT PRIMARY KEY,
            umo        TEXT NOT NULL,
            persona_id TEXT NOT NULL,
            delta      REAL NOT NULL,
            reason     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_affinity_ledger_umo
            ON affinity_ledger (umo, persona_id);

        CREATE TABLE IF NOT EXISTS interaction_stats (
            umo           TEXT NOT NULL,
            persona_id    TEXT NOT NULL,
            day           TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            last_at       TEXT,
            PRIMARY KEY (umo, persona_id, day)
        );

        CREATE TABLE IF NOT EXISTS open_threads (
            thread_id  TEXT PRIMARY KEY,
            umo        TEXT NOT NULL,
            persona_id TEXT NOT NULL,
            title      TEXT NOT NULL DEFAULT '',
            status     TEXT NOT NULL DEFAULT 'open',
            opened_at  TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_open_threads_umo
            ON open_threads (umo, persona_id, status);

        CREATE TABLE IF NOT EXISTS motivation_log (
            entry_id   TEXT PRIMARY KEY,
            persona_id TEXT NOT NULL,
            kind       TEXT NOT NULL,
            value      REAL NOT NULL DEFAULT 0,
            reason     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        -- v2: real relationship model keyed by (persona_id, user_id).
        -- v1's placeholder tables only ever held derived values, so a rebuild
        -- is safe (no message bodies, no production data at v1 release).
        DROP TABLE IF EXISTS relationships;
        CREATE TABLE relationships (
            persona_id      TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            affinity        REAL NOT NULL DEFAULT 0,
            stage           TEXT NOT NULL DEFAULT '陌生',
            bond            INTEGER NOT NULL DEFAULT 0,
            last_active_day TEXT,
            last_decay_day  TEXT,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (persona_id, user_id)
        );

        DROP TABLE IF EXISTS affinity_ledger;
        CREATE TABLE affinity_ledger (
            persona_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            event_id   TEXT NOT NULL,
            delta      REAL NOT NULL,
            reason     TEXT NOT NULL DEFAULT '',
            day        TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (persona_id, user_id, event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_affinity_ledger_daily
            ON affinity_ledger (persona_id, user_id, day);

        DROP TABLE IF EXISTS interaction_stats;
        CREATE TABLE interaction_stats (
            persona_id           TEXT NOT NULL,
            user_id              TEXT NOT NULL,
            message_count        INTEGER NOT NULL DEFAULT 0,
            proactive_sent       INTEGER NOT NULL DEFAULT 0,
            proactive_replied    INTEGER NOT NULL DEFAULT 0,
            unanswered_streak    INTEGER NOT NULL DEFAULT 0,
            reply_delay_sum      REAL NOT NULL DEFAULT 0,
            reply_delay_count    INTEGER NOT NULL DEFAULT 0,
            pending_proactive_at TEXT,
            last_interaction_at  TEXT,
            updated_at           TEXT NOT NULL,
            PRIMARY KEY (persona_id, user_id)
        );
        """,
    ),
    (
        3,
        """
        -- v3: motivation/open-thread audit columns (T3).
        -- motivation_log gains a per-user scope, the scored candidate set and
        -- the decision outcome. Still derived values only: no message bodies.
        ALTER TABLE motivation_log ADD COLUMN umo TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN user_id TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN candidates_json TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN selected_reason TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN adopted INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE motivation_log ADD COLUMN blocked_reason TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN reason_code TEXT NOT NULL DEFAULT '';
        ALTER TABLE motivation_log ADD COLUMN receipt_key TEXT;
        CREATE INDEX IF NOT EXISTS idx_motivation_log_scope
            ON motivation_log (persona_id, user_id, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_motivation_log_receipt
            ON motivation_log (persona_id, user_id, receipt_key);

        -- open_threads stays a short-label table; index scopes label lookups.
        CREATE INDEX IF NOT EXISTS idx_open_threads_scope
            ON open_threads (umo, status, updated_at);
        """,
    ),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
)

#: All tables that must exist after migration, used by tests/health checks.
EXPECTED_TABLES: tuple[str, ...] = (
    "schema_meta",
    "personas",
    "life_state_daily",
    "life_schedule",
    "relationships",
    "affinity_ledger",
    "interaction_stats",
    "open_threads",
    "motivation_log",
    "emotion_events",
    "sleep_windows",
    "life_events",
    "life_diary",
    "group_activity",
    "group_members",
    "growth_state",
)


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the recorded schema version (0 when uninitialised)."""
    _ensure_meta_table(conn)
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(version),),
    )


def apply_migrations(conn: sqlite3.Connection, target: int = SCHEMA_VERSION) -> int:
    """Apply pending migrations up to ``target``. Idempotent.

    Returns the resulting schema version.
    """
    current = get_schema_version(conn)
    for version, step in MIGRATIONS:
        if current < version <= target:
            if callable(step):
                step(conn)
            else:
                conn.executescript(step)
            _set_schema_version(conn, version)
            current = version
    conn.commit()
    return current


def connect(
    db_path: str | None = None,
) -> sqlite3.Connection:
    """Open a connection with the plugin's standard pragmas, no migration."""
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if db_path:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn
