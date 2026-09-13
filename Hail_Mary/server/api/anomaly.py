"""POST /api/v1/anomaly, GET /api/v1/anomaly, POST /api/v1/anomaly/{event_id}/ack
(문서/개발_기능명세서.md 6장). Persists/reads M7 Anomaly Detector output
(core.anomaly_detector.detect_anomalies() produces exactly the POST body
shape below -- code review 2026-09-13 found that function had no HTTP route
feeding its output in anywhere, the M7 counterpart to how POST
/api/v1/occupancy ingests M2/M3 edge uplink batches)."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from Hail_Mary.server.api.deps import get_db, require_api_key

router = APIRouter(prefix="/api/v1/anomaly", tags=["anomaly"])


class AnomalyEventIn(BaseModel):
    event_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)
    ts: str = Field(min_length=1)
    # allow_inf_nan=False: Infinity is a legal IEEE-754 double (and
    # json.loads() accepts the literal "Infinity"/"NaN" by default), so
    # without this it would insert successfully and then permanently 500
    # every later GET /api/v1/anomaly for everyone -- Starlette's
    # JSONResponse.render() calls json.dumps(..., allow_nan=False), with no
    # exception handler anywhere to catch that (code review 2026-09-14).
    residual_kwh: float = Field(allow_inf_nan=False)
    occupancy_at_ts: int = Field(ge=0)
    severity: str = Field(min_length=1)
    resolved: bool = False


class AnomalyBatchUploadResponse(BaseModel):
    inserted: int
    received: int


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


@router.post("", response_model=AnomalyBatchUploadResponse, dependencies=[Depends(require_api_key)])
def upload_anomaly_batch(events: list[AnomalyEventIn], conn: sqlite3.Connection = Depends(get_db)):
    payload = [event.model_dump() for event in events]
    inserted = insert_anomaly_events(conn, payload)
    return AnomalyBatchUploadResponse(inserted=inserted, received=len(events))


@router.get("")
def get_anomalies(status: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)):
    return query_anomalies(conn, status=status)


@router.post("/{event_id}/ack")  # no API key: called directly by the browser dashboard's "확인" button (app.js),
# which has no secure place to hold a secret -- same reasoning as GETs, see require_api_key()'s docstring.
def ack_anomaly(event_id: str, conn: sqlite3.Connection = Depends(get_db)):
    if not acknowledge_anomaly(conn, event_id):
        raise HTTPException(status_code=404, detail="anomaly event not found")
    return {"event_id": event_id, "resolved": True}
