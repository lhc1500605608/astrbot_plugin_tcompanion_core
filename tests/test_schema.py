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
