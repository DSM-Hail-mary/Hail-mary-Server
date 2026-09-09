"""Red-Green-Refactor: DB connection helper used by the FastAPI app and by
data-loading scripts (Feature Store). Real SQLite file on disk, no mocking."""
import sqlite3

from Hail_Mary.server.db.connection import open_database


def test_open_database_creates_file_and_all_tables(tmp_path):
    db_path = tmp_path / "nested" / "hail_mary.db"

    conn = open_database(db_path)

    assert db_path.exists()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"occupancy", "power_reading", "forecast", "anomaly_event", "notification_log"} <= tables
    conn.close()


def test_open_database_rows_are_dict_like(tmp_path):
    conn = open_database(tmp_path / "hail_mary.db")
    conn.execute(
        "INSERT INTO occupancy (zone_id, window_start, window_end, count) VALUES (?, ?, ?, ?)",
        ("hall_main", "2026-08-21T10:00:00Z", "2026-08-21T10:01:00Z", 3),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM occupancy").fetchone()

    assert row["zone_id"] == "hall_main"
    assert row["count"] == 3
    conn.close()


def test_open_database_reopens_existing_file_without_data_loss(tmp_path):
    db_path = tmp_path / "hail_mary.db"
    conn1 = open_database(db_path)
    conn1.execute(
        "INSERT INTO power_reading (building_id, ts, kwh) VALUES (?, ?, ?)",
        ("b1", "2026-08-21T10:00:00Z", 12.4),
    )
    conn1.commit()
    conn1.close()

    conn2 = open_database(db_path)
    row = conn2.execute("SELECT kwh FROM power_reading WHERE building_id='b1'").fetchone()

    assert row["kwh"] == 12.4
    conn2.close()


def test_open_database_returns_sqlite_connection(tmp_path):
    conn = open_database(tmp_path / "hail_mary.db")
    assert isinstance(conn, sqlite3.Connection)
    conn.close()
