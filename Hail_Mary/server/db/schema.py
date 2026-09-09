"""SQLite schema for the Hail-Mary backend server (M4~M10 data layer).

Seven tables, matching 문서/제안서_백엔드추가.md 4.4.3 / 문서/개발_기능명세서.md 5장:

  occupancy        -- M2/M3 edge -> server ingestion (POST /api/v1/occupancy)
  power_reading    -- public dataset (BDG2) ingestion for the Feature Store
  forecast         -- Forecast Engine output (with/without occupancy)
  anomaly_event    -- Anomaly Detector output
  notification_log -- Notification Service delivery log
  savings_report   -- M8 Savings/Carbon Calculator output
  last_seen_image  -- dashboard "마지막 목격 이미지" card (1 image per zone_id)
"""
import sqlite3

EXPECTED_TABLES = (
    "occupancy",
    "power_reading",
    "forecast",
    "anomaly_event",
    "notification_log",
    "savings_report",
    "last_seen_image",
)

_DDL = """
CREATE TABLE IF NOT EXISTS occupancy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    count INTEGER NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (zone_id, window_start, window_end)
);

CREATE TABLE IF NOT EXISTS power_reading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kwh REAL NOT NULL,
    UNIQUE (building_id, ts)
);

CREATE TABLE IF NOT EXISTS forecast (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id TEXT NOT NULL,
    target_ts TEXT NOT NULL,
    with_occ_kwh REAL,
    without_occ_kwh REAL,
    actual_kwh REAL,
    generated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (building_id, target_ts, generated_at)
);

CREATE TABLE IF NOT EXISTS anomaly_event (
    event_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    residual_kwh REAL NOT NULL,
    occupancy_at_ts INTEGER NOT NULL,
    severity TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS savings_report (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    saved_kwh REAL NOT NULL,
    saved_pct REAL NOT NULL,
    co2_kg REAL NOT NULL,
    tree_equivalent REAL NOT NULL,
    UNIQUE (period_start, period_end)
);

CREATE TABLE IF NOT EXISTS last_seen_image (
    zone_id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    image_path TEXT NOT NULL
);
"""


def init_db(connection: sqlite3.Connection) -> None:
    """Create the tables if they do not already exist. Idempotent."""
    connection.executescript(_DDL)
    connection.commit()
