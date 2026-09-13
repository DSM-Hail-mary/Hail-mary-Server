"""POST /api/v1/savings, GET /api/v1/savings (문서/개발_기능명세서.md 6장, M8).

POST computes an M8 savings/carbon report from two real, caller-supplied kWh
series (see core.savings for why the control-simulation series is an input
here rather than something this module derives) and persists it.
"""
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from Hail_Mary.server.api.deps import get_db, require_api_key
from Hail_Mary.server.core.savings import compute_savings

router = APIRouter(prefix="/api/v1/savings", tags=["savings"])


class SavingsComputeRequest(BaseModel):
    period_start: str = Field(min_length=1)
    period_end: str = Field(min_length=1)
    actual_kwh: List[float]
    simulated_kwh: List[float]

    @model_validator(mode="after")
    def _series_same_length(self):
        if len(self.actual_kwh) != len(self.simulated_kwh):
            raise ValueError("actual_kwh and simulated_kwh must be the same length")
        if not self.actual_kwh:
            raise ValueError("need at least one reading in each series")
        return self


class SavingsReport(BaseModel):
    period_start: str
    period_end: str
    saved_kwh: float
    saved_pct: float
    co2_kg: float
    tree_equivalent: float


def insert_savings_report(conn: sqlite3.Connection, report: dict) -> bool:
    """Idempotent by (period_start, period_end). Returns True if a new row
    was inserted, False if that period was already reported."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO savings_report "
        "(period_start, period_end, saved_kwh, saved_pct, co2_kg, tree_equivalent) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (report["period_start"], report["period_end"], report["saved_kwh"],
         report["saved_pct"], report["co2_kg"], report["tree_equivalent"]),
    )
    conn.commit()
    return cursor.rowcount > 0


def query_savings_reports(conn: sqlite3.Connection, period_start: Optional[str] = None) -> list:
    query = ("SELECT period_start, period_end, saved_kwh, saved_pct, co2_kg, tree_equivalent "
             "FROM savings_report")
    params: list = []
    if period_start is not None:
        query += " WHERE period_start = ?"
        params.append(period_start)
    query += " ORDER BY period_start ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


@router.post("", response_model=SavingsReport, dependencies=[Depends(require_api_key)])
def post_savings(body: SavingsComputeRequest, conn: sqlite3.Connection = Depends(get_db)):
    report = compute_savings(
        period_start=body.period_start, period_end=body.period_end,
        actual_kwh_series=body.actual_kwh, simulated_kwh_series=body.simulated_kwh,
    )
    insert_savings_report(conn, report)
    return report


@router.get("", response_model=List[SavingsReport])
def get_savings(period_start: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)):
    return query_savings_reports(conn, period_start=period_start)
