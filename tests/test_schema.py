from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core import db as schema
from core.life_state import WeeklySchedule, generate_life_state
from core.store import Store


def test_schema_creates_all_expected_tables(store):
    assert set(schema.EXPECTED_TABLES).issubset(store.table_names())
    assert store.schema_version == schema.SCHEMA_VERSION


def test_migration_is_idempotent(store):
    version_before = store.schema_version
    for _ in range(3):
        assert store.migrate() == version_before
    assert store.schema_version == version_before
    assert set(schema.EXPECTED_TABLES).issubset(store.table_names())


def test_migrate_on_raw_connection_twice(tmp_path):
    db_file = tmp_path / "nested" / "core.sqlite3"
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = schema.connect(str(db_file))
    try:
        first = schema.apply_migrations(conn)
        second = schema.apply_migrations(conn)
    finally:
        conn.close()

    assert first == second == schema.SCHEMA_VERSION

    conn = schema.connect(str(db_file))
    try:
        assert schema.get_schema_version(conn) == schema.SCHEMA_VERSION
    finally:
        conn.close()


def test_no_message_body_columns(store):
    """Privacy invariant: no table may hold raw message text."""
    forbidden = {"content", "text", "message", "raw", "body", "msg"}
    for table in schema.EXPECTED_TABLES:
        cols = {row[1] for row in store.connection.execute(f"PRAGMA table_info({table})")}
        assert not (cols & forbidden), f"{table} exposes message-body columns: {cols}"


def test_store_roundtrip_life_state(store):
    schedule = WeeklySchedule.default_template("p1")
    moment = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)  # Monday
    state = generate_life_state(schedule, "p1", moment)
    store.upsert_life_state(state)

    row = store.get_life_state("p1", "2026-09-21")
    assert row is not None
    assert row["activity"] == "working"
    assert row["scene"] == "desk"


def test_legacy_connection_still_usable(store):
    assert isinstance(store.connection, sqlite3.Connection)


def test_open_explicit_path_creates_parent_dirs(tmp_path):
    """Regression: AstrBot 4.28.1 does not pre-create the per-plugin data dir."""
    db_file = tmp_path / "plugin_data" / "astrbot_plugin_tcompanion_core" / "core.sqlite3"
    assert not db_file.parent.exists()

    s = Store.open(db_file)
    try:
        assert db_file.exists()
        assert s.schema_version == schema.SCHEMA_VERSION
    finally:
        s.close()


def test_open_memory_needs_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Store.open(":memory:")
    try:
        assert s.schema_version == schema.SCHEMA_VERSION
    finally:
        s.close()
    assert list(tmp_path.iterdir()) == []


# -- schema v5 (open-thread lifecycle) ------------------------------------
def test_schema_v5_open_thread_columns(store):
    cols = {row[1] for row in store.connection.execute("PRAGMA table_info(open_threads)")}
    assert set(schema.V5_OPEN_THREAD_COLUMNS) <= cols


def test_migrate_v4_to_v5_in_place_preserves_and_backfills(tmp_path):
    """Old v4 rows survive the upgrade; new columns take defaults + backfill."""
    db_file = tmp_path / "v4.sqlite3"
    conn = schema.connect(str(db_file))
    try:
        assert schema.apply_migrations(conn, target=4) == 4
        conn.execute(
            "INSERT INTO open_threads "
            "(thread_id, umo, persona_id, title, status, opened_at, updated_at) "
            "VALUES ('legacy', 'umo://u', 'p1', '旧话题', 'open', "
            "'2026-09-10T10:00:00+00:00', '2026-09-11T10:00:00+00:00')"
        )
        conn.commit()

        assert schema.apply_migrations(conn) == schema.SCHEMA_VERSION
        row = conn.execute("SELECT * FROM open_threads WHERE thread_id = 'legacy'").fetchone()
        # old row untouched
        assert row["title"] == "旧话题"
        assert row["status"] == "open"
        assert row["opened_at"] == "2026-09-10T10:00:00+00:00"
        # new columns defaulted, last_seen_ts backfilled from updated_at
        assert row["kind"] == "topic"
        assert row["followup_count"] == 0
        assert row["last_followup_ts"] == ""
        assert row["closed_reason"] == ""
        assert row["dedupe_key"] is None
        assert row["last_seen_ts"] == "2026-09-11T10:00:00+00:00"
    finally:
        conn.close()


def test_v5_migration_is_idempotent(tmp_path):
    db_file = tmp_path / "v5.sqlite3"
    conn = schema.connect(str(db_file))
    try:
        assert schema.apply_migrations(conn) == schema.SCHEMA_VERSION
        for _ in range(3):
            schema._migrate_v5(conn)
        assert schema.apply_migrations(conn) == schema.SCHEMA_VERSION
    finally:
        conn.close()


# -- schema v6 (life line) ------------------------------------------------
def test_schema_v6_life_line_tables(store):
    assert schema.SCHEMA_VERSION >= 6
    assert {"sleep_windows", "life_events", "life_diary"} <= store.table_names()


def test_migrate_v5_to_v6_in_place_preserves_and_adds(tmp_path):
    """Old v5 rows survive; the three new tables start empty; idempotent."""
    db_file = tmp_path / "v5.sqlite3"
    conn = schema.connect(str(db_file))
    try:
        assert schema.apply_migrations(conn, target=5) == 5
        conn.execute(
            "INSERT INTO open_threads "
            "(thread_id, umo, persona_id, title, status, opened_at, updated_at) "
            "VALUES ('legacy', 'umo://u', 'p1', '旧话题', 'open', "
            "'2026-09-10T10:00:00+00:00', '2026-09-11T10:00:00+00:00')"
        )
        conn.commit()

        assert schema.apply_migrations(conn, target=6) == 6
        row = conn.execute("SELECT * FROM open_threads WHERE thread_id = 'legacy'").fetchone()
        assert row["title"] == "旧话题"
        assert row["status"] == "open"
        for table in ("sleep_windows", "life_events", "life_diary"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

        # re-running is a no-op and never touches existing rows
        for _ in range(3):
            schema._migrate_v6(conn)
        assert schema.apply_migrations(conn, target=6) == 6
        assert conn.execute("SELECT COUNT(*) FROM open_threads").fetchone()[0] == 1
    finally:
        conn.close()


# -- schema v7 (group + growth) -------------------------------------------
def test_schema_v7_group_and_growth_tables(store):
    assert store.schema_version == schema.SCHEMA_VERSION == 7
    assert {"group_activity", "group_members", "growth_state"} <= store.table_names()


def test_migrate_v6_to_v7_in_place_preserves_and_adds(tmp_path):
    """Old v6 rows survive; the three new tables start empty; idempotent."""
    db_file = tmp_path / "v6.sqlite3"
    conn = schema.connect(str(db_file))
    try:
        assert schema.apply_migrations(conn, target=6) == 6
        conn.execute(
            "INSERT INTO open_threads "
            "(thread_id, umo, persona_id, title, status, opened_at, updated_at) "
            "VALUES ('legacy', 'umo://u', 'p1', '旧话题', 'open', "
            "'2026-09-10T10:00:00+00:00', '2026-09-11T10:00:00+00:00')"
        )
        conn.commit()

        assert schema.apply_migrations(conn) == schema.SCHEMA_VERSION == 7
        row = conn.execute("SELECT * FROM open_threads WHERE thread_id = 'legacy'").fetchone()
        assert row["title"] == "旧话题"
        for table in ("group_activity", "group_members", "growth_state"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

        for _ in range(3):
            schema._migrate_v7(conn)
        assert schema.apply_migrations(conn) == 7
        assert conn.execute("SELECT COUNT(*) FROM open_threads").fetchone()[0] == 1
    finally:
        conn.close()


def test_life_diary_is_idempotent_and_unique(store):
    assert store.insert_diary("p1", "u1", "2026-09-20", summary="a", mood="平静") is True
    assert store.insert_diary("p1", "u1", "2026-09-20", summary="b", mood="开心") is False
    row = store.get_diary("p1", "u1", "2026-09-20")
    assert row["summary"] == "a" and row["mood"] == "平静"


def test_insert_life_event_dedupes(store):
    stamp = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    assert store.insert_life_event(
        "p1", "u1", kind="meal", dedupe_key="meal:lunch:2026-09-20", ts=stamp
    ) is True
    assert store.insert_life_event(
        "p1", "u1", kind="meal", dedupe_key="meal:lunch:2026-09-20", ts=stamp
    ) is False
    rows = store.list_life_events("p1", "u1", day="2026-09-20", kind="meal")
    assert len(rows) == 1
    assert store.get_sleep_window("p1", "u1", "2026-09-20") is None
    store.upsert_sleep_window("p1", "u1", "2026-09-20", start_min=1380, end_min=450, source="default")
    # auto rows never clobber an existing row
    store.upsert_sleep_window("p1", "u1", "2026-09-20", start_min=0, end_min=60, source="inferred")
    assert store.get_sleep_window("p1", "u1", "2026-09-20")["start_min"] == 1380


def test_open_threads_store_no_message_body(store):
    """Privacy: still no raw-text column; titles are sanitized short labels."""
    cols = {row[1] for row in store.connection.execute("PRAGMA table_info(open_threads)")}
    assert not (cols & {"content", "text", "message", "raw", "body", "msg"})
    row = store.upsert_open_thread("t1", "umo://u", "p1", "x" * 200)
    assert len(row["title"]) <= 40
    assert row["title"].endswith("…")


def test_upsert_open_thread_bumps_instead_of_inserting(store):
    first = store.upsert_open_thread(
        "t1", "umo://u", "p1", "旧标签", kind="plan", confidence=0.8,
        now=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
    )
    second = store.upsert_open_thread(
        "t1", "umo://u", "p1", "新标签", kind="commitment", confidence=0.9,
        now=datetime(2026, 9, 21, 10, tzinfo=timezone.utc),
    )
    assert first["thread_id"] == second["thread_id"] == "t1"
    rows = store.list_open_thread_details("umo://u", "p1")
    assert len(rows) == 1
    assert rows[0]["title"] == "新标签"
    assert rows[0]["kind"] == "commitment"
    assert rows[0]["last_seen_ts"] == "2026-09-21T10:00:00+00:00"


def test_touch_mark_followup_and_close(store):
    store.upsert_open_thread("t1", "umo://u", "p1", "话题", now=datetime(2026, 9, 20, tzinfo=timezone.utc))

    assert store.mark_thread_followup(
        "t1", umo="umo://u", now=datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    )["followup_count"] == 1
    row = store.mark_thread_followup(
        "t1", umo="umo://u", now=datetime(2026, 9, 20, 13, tzinfo=timezone.utc)
    )
    assert row["followup_count"] == 2
    assert row["last_followup_ts"] == "2026-09-20T13:00:00+00:00"
    # wrong scope must not touch the row
    assert store.mark_thread_followup("t1", umo="other") is None

    assert store.touch_open_thread(
        "t1", umo="umo://u", now=datetime(2026, 9, 21, tzinfo=timezone.utc)
    )
    assert store.list_open_thread_details("umo://u", "p1")[0]["last_seen_ts"] == (
        "2026-09-21T00:00:00+00:00"
    )

    assert store.close_open_thread(
        "t1", datetime(2026, 9, 21, 1, tzinfo=timezone.utc), umo="umo://u", reason="answered"
    )
    closed = store.list_open_thread_details("umo://u", "p1", status="closed")[0]
    assert closed["closed_reason"] == "answered"
    # scoped close does not match another umo
    assert not store.close_open_thread("t1", umo="other", reason="x")


def test_expire_open_threads_ttl_stale_and_expire_closed(store):
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    store.upsert_open_thread(
        "fresh", "umo://u", "p1", "新", now=datetime(2026, 9, 21, 11, tzinfo=timezone.utc)
    )
    store.upsert_open_thread(
        "old", "umo://u", "p1", "旧", now=datetime(2026, 9, 15, tzinfo=timezone.utc)
    )
    store.upsert_open_thread(
        "ancient", "umo://u", "p1", "远古", now=datetime(2026, 8, 1, tzinfo=timezone.utc)
    )

    counts = store.expire_open_threads(now, ttl_days=3, expire_days=14)
    assert counts["stale"] == 1  # "old" -> stale
    assert counts["expired"] == 1  # "ancient" -> closed(expired)

    by_id = {row["thread_id"]: row for row in store.list_open_thread_details("umo://u", "p1")}
    assert by_id["fresh"]["status"] == "open"
    assert by_id["old"]["status"] == "stale"
    assert by_id["ancient"]["status"] == "closed"
    assert by_id["ancient"]["closed_reason"] == "expired"


def test_expire_open_threads_lru_eviction(store):
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    for i in range(5):
        store.upsert_open_thread(
            f"t{i}",
            "umo://u",
            "p1",
            f"标签{i}",
            now=datetime(2026, 9, 21, 12 - i, tzinfo=timezone.utc),
        )
    counts = store.expire_open_threads(now, ttl_days=30, expire_days=60, max_open=3)
    assert counts["evicted"] == 2
    open_rows = store.list_open_thread_details("umo://u", "p1", status="open")
    assert [row["thread_id"] for row in open_rows] == ["t0", "t1", "t2"]
    evicted = store.list_open_thread_details("umo://u", "p1", status="closed")
    assert {row["closed_reason"] for row in evicted} == {"superseded"}
