"""GET /api/v1/anomaly, POST /api/v1/anomaly/{event_id}/ack (문서/개발_기능명세서.md
6장). Persists/reads M7 Anomaly Detector output (core.anomaly_detector)."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api/v1/anomaly", tags=["anomaly"])


def insert_anomaly_events(conn: sqlite3.Connection, events: list) -> int:
    inserted = 0
    for event in events:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO anomaly_event "
            "(event_id, zone_id, ts, residual_kwh, occupancy_at_ts, severity, resolved) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event["event_id"], event["zone_id"], event["ts"], event["residual_kwh"],
             event["occupancy_at_ts"], event["severity"], int(event.get("resolved", False))),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def query_anomalies(conn: sqlite3.Connection, status: Optional[str] = None) -> list:
    query = "SELECT event_id, zone_id, ts, residual_kwh, occupancy_at_ts, severity, resolved FROM anomaly_event"
    params: list = []
    if status == "open":
        query += " WHERE resolved = 0"
    elif status == "resolved":
        query += " WHERE resolved = 1"
    query += " ORDER BY ts ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def acknowledge_anomaly(conn: sqlite3.Connection, event_id: str) -> bool:
    cursor = conn.execute("UPDATE anomaly_event SET resolved = 1 WHERE event_id = ?", (event_id,))
    conn.commit()
    return cursor.rowcount > 0


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.get("")
def get_anomalies(status: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)):
    return query_anomalies(conn, status=status)


@router.post("/{event_id}/ack")
def ack_anomaly(event_id: str, conn: sqlite3.Connection = Depends(get_db)):
    if not acknowledge_anomaly(conn, event_id):
        raise HTTPException(status_code=404, detail="anomaly event not found")
    return {"event_id": event_id, "resolved": True}
