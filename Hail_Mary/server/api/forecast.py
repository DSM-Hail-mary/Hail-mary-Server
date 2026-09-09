"""GET /api/v1/forecast, GET /api/v1/forecast/ablation (문서/개발_기능명세서.md
6장). Both endpoints read pre-computed rows from the `forecast` table
(populated by core.forecast_engine.forecast_with_and_without_occupancy via
insert_forecast_rows) rather than running the model inline, matching the
"예측 API 응답시간 ≤1s (사전 계산된 예측값 조회 기준)" requirement in 4.4.5.
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Request

from Hail_Mary.server.core.ablation import evaluate_ablation

router = APIRouter(prefix="/api/v1/forecast", tags=["forecast"])


def insert_forecast_rows(conn: sqlite3.Connection, generated_at: str, rows: list) -> int:
    inserted = 0
    for row in rows:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO forecast "
            "(building_id, target_ts, with_occ_kwh, without_occ_kwh, actual_kwh, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["building_id"], row["target_ts"], row.get("with_occ_kwh"),
             row["without_occ_kwh"], row.get("actual_kwh"), generated_at),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def query_forecast(conn: sqlite3.Connection, building_id: str, horizon: Optional[int] = None) -> list:
    """Rows from the most recently generated forecast batch for building_id,
    ordered by target_ts ascending, optionally limited to the first
    `horizon` rows."""
    latest = conn.execute(
        "SELECT MAX(generated_at) AS g FROM forecast WHERE building_id = ?", (building_id,)
    ).fetchone()
    if latest is None or latest["g"] is None:
        return []

    query = (
        "SELECT building_id, target_ts, with_occ_kwh, without_occ_kwh, actual_kwh, generated_at "
        "FROM forecast WHERE building_id = ? AND generated_at = ? ORDER BY target_ts ASC"
    )
    params = [building_id, latest["g"]]
    if horizon is not None:
        query += " LIMIT ?"
        params.append(horizon)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def query_forecast_rows_with_actual(
    conn: sqlite3.Connection, building_id: Optional[str] = None, period: Optional[str] = None
) -> list:
    """Rows with a known actual_kwh (i.e. usable for ablation scoring),
    optionally filtered to one building and/or a target_ts date prefix
    (e.g. period="2017-01" for January 2017, "2017-01-06" for one day)."""
    query = "SELECT building_id, target_ts, with_occ_kwh, without_occ_kwh, actual_kwh FROM forecast WHERE actual_kwh IS NOT NULL"
    params: list = []
    if building_id is not None:
        query += " AND building_id = ?"
        params.append(building_id)
    if period is not None:
        query += " AND target_ts LIKE ?"
        params.append(f"{period}%")
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.get("")
def get_forecast(building_id: str, horizon: Optional[int] = None, conn: sqlite3.Connection = Depends(get_db)):
    return query_forecast(conn, building_id=building_id, horizon=horizon)


@router.get("/ablation")
def get_forecast_ablation(
    building_id: Optional[str] = None, period: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)
):
    rows = query_forecast_rows_with_actual(conn, building_id=building_id, period=period)
    return evaluate_ablation(rows)
