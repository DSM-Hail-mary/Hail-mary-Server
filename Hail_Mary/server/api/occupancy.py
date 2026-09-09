"""M2/M3 edge -> server occupancy ingestion (문서/개발_기능명세서.md 6장).

Payload schema is the exact contract in Hail_Mary/edge/uplink.py's
build_occupancy_payload(): a JSON array of
{zone_id: str, window_start: ISO8601 str, window_end: ISO8601 str, count: int}.
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/occupancy", tags=["occupancy"])


class OccupancyRecord(BaseModel):
    zone_id: str = Field(min_length=1)
    window_start: str = Field(min_length=1)
    window_end: str = Field(min_length=1)
    count: int = Field(ge=0)


class OccupancyBatchUploadResponse(BaseModel):
    inserted: int
    received: int


class LiveOccupancy(BaseModel):
    zone_id: str
    window_start: str
    window_end: str
    count: int


def insert_occupancy_batch(conn: sqlite3.Connection, records: list) -> int:
    """Insert occupancy rows, skipping any (zone_id, window_start, window_end)
    already present so a retried HTTP batch (edge/uplink.py backoff retry) is
    idempotent. Returns the number of newly inserted rows.

    Raises ValueError on malformed records (empty zone_id / negative count) --
    those are logic errors distinct from "already seen", so they are not
    silently swallowed like duplicates are.
    """
    for record in records:
        if not record.get("zone_id"):
            raise ValueError("zone_id must be non-empty")
        if record.get("count", -1) < 0:
            raise ValueError("count must be >= 0")

    inserted = 0
    for record in records:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO occupancy (zone_id, window_start, window_end, count) "
            "VALUES (?, ?, ?, ?)",
            (record["zone_id"], record["window_start"], record["window_end"], record["count"]),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def latest_occupancy(conn: sqlite3.Connection, zone_id: Optional[str] = None):
    """Return the most-recent-window occupancy row (by window_end) for a given
    zone_id, or for every zone if zone_id is None."""
    if zone_id is not None:
        row = conn.execute(
            "SELECT zone_id, window_start, window_end, count FROM occupancy "
            "WHERE zone_id = ? ORDER BY window_end DESC LIMIT 1",
            (zone_id,),
        ).fetchone()
        return dict(row) if row else None

    rows = conn.execute(
        "SELECT zone_id, window_start, window_end, count FROM occupancy o "
        "WHERE window_end = (SELECT MAX(window_end) FROM occupancy WHERE zone_id = o.zone_id) "
        "GROUP BY zone_id"
    ).fetchall()
    return [dict(row) for row in rows]


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.post("", response_model=OccupancyBatchUploadResponse)
def upload_occupancy_batch(records: list[OccupancyRecord], conn: sqlite3.Connection = Depends(get_db)):
    payload = [record.model_dump() for record in records]
    inserted = insert_occupancy_batch(conn, payload)
    return OccupancyBatchUploadResponse(inserted=inserted, received=len(records))


@router.get("/live")
def get_live_occupancy(zone_id: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)):
    result = latest_occupancy(conn, zone_id=zone_id)
    if zone_id is not None:
        return result
    return result
