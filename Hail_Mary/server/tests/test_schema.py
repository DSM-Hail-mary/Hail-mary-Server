"""Red-Green-Refactor: DB schema (5 tables from 문서/제안서_백엔드추가.md 4.4.3).

Uses a real temp SQLite file on disk (no mocking) and asserts the actual
table/column shape created by db.schema.init_db().
"""
import sqlite3

import pytest

from Hail_Mary.server.db.schema import EXPECTED_TABLES, init_db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "hail_mary_test.db"
    connection = sqlite3.connect(str(db_path))
    init_db(connection)
    yield connection
    connection.close()


def _columns(conn, table):
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def test_creates_all_five_tables(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {row[0] for row in cursor.fetchall()}
    for expected in EXPECTED_TABLES:
        assert expected in table_names


def test_occupancy_table_columns(conn):
    columns = _columns(conn, "occupancy")
    assert {"zone_id", "window_start", "window_end", "count"} <= columns


def test_power_reading_table_columns(conn):
    columns = _columns(conn, "power_reading")
    assert {"building_id", "ts", "kwh"} <= columns


def test_forecast_table_columns(conn):
    columns = _columns(conn, "forecast")
    assert {"building_id", "target_ts", "with_occ_kwh", "without_occ_kwh", "actual_kwh"} <= columns


def test_anomaly_event_table_columns(conn):
    columns = _columns(conn, "anomaly_event")
    assert {"event_id", "zone_id", "ts", "residual_kwh", "occupancy_at_ts", "severity", "resolved"} <= columns


def test_notification_log_table_columns(conn):
    columns = _columns(conn, "notification_log")
    assert {"event_id", "channel", "sent_at", "status"} <= columns


def test_init_db_is_idempotent(conn):
    # Calling init_db a second time on an already-initialized connection
    # must not raise (CREATE TABLE IF NOT EXISTS semantics).
    init_db(conn)


def test_occupancy_rejects_duplicate_zone_window(conn):
    conn.execute(
        "INSERT INTO occupancy (zone_id, window_start, window_end, count) VALUES (?, ?, ?, ?)",
        ("hall_main", "2026-08-21T10:00:00Z", "2026-08-21T10:01:00Z", 3),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO occupancy (zone_id, window_start, window_end, count) VALUES (?, ?, ?, ?)",
            ("hall_main", "2026-08-21T10:00:00Z", "2026-08-21T10:01:00Z", 5),
        )


def test_power_reading_rejects_duplicate_building_ts(conn):
    conn.execute(
        "INSERT INTO power_reading (building_id, ts, kwh) VALUES (?, ?, ?)",
        ("b1", "2026-08-21T10:00:00Z", 12.4),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO power_reading (building_id, ts, kwh) VALUES (?, ?, ?)",
            ("b1", "2026-08-21T10:00:00Z", 99.9),
        )
