"""M4 Feature Store (문서/개발_기능명세서.md 4장 M4): aligns occupancy + public
power data + calendar/weather onto one common hourly timestamp grid, per the
target feature table `timestamp, building_id, zone_id, power_kwh, occupancy,
hour, dow, is_holiday, temp` from 4.4.2/4.4.3.
"""
import datetime as dt
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd


def resample_occupancy_to_hourly(occupancy_rows: List[dict], zone_id: str) -> Dict[str, float]:
    """1분 집계값을 1시간 평균으로 축약 (개발_기능명세서.md M4). Only rows for the
    given zone_id are used; window_start is truncated to the hour and values
    within that hour are averaged."""
    buckets: Dict[str, List[float]] = defaultdict(list)
    for row in occupancy_rows:
        if row["zone_id"] != zone_id:
            continue
        hour_ts = row["window_start"][:13] + ":00:00"
        buckets[hour_ts].append(row["count"])
    return {hour_ts: sum(values) / len(values) for hour_ts, values in buckets.items()}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """weekday: Monday=0..Sunday=6. n-th occurrence in the month (1-indexed)."""
    d = dt.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d += dt.timedelta(days=offset + 7 * (n - 1))
    return d


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    if month == 12:
        d = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - dt.timedelta(days=offset)


def _is_us_federal_holiday(date: dt.date) -> bool:
    """Real US federal holiday calendar, computed from the actual rules (no
    external data source needed / no network dependency). Note: this checks
    the holiday's actual calendar date, not the "observed" date the federal
    government shifts a holiday to when it falls on a weekend -- for a
    demand-pattern feature, the true date is what matters."""
    year = date.year
    fixed = {
        dt.date(year, 1, 1),   # New Year's Day
        dt.date(year, 7, 4),   # Independence Day
        dt.date(year, 11, 11),  # Veterans Day
        dt.date(year, 12, 25),  # Christmas
    }
    floating = {
        _nth_weekday(year, 1, 0, 3),   # MLK Day: 3rd Monday of January
        _nth_weekday(year, 2, 0, 3),   # Presidents Day: 3rd Monday of February
        _last_weekday(year, 5, 0),     # Memorial Day: last Monday of May
        _nth_weekday(year, 9, 0, 1),   # Labor Day: 1st Monday of September
        _nth_weekday(year, 10, 0, 2),  # Columbus Day: 2nd Monday of October
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving: 4th Thursday of November
    }
    return date in fixed or date in floating


def build_calendar_features(timestamps: List[str]) -> List[dict]:
    """hour (0-23), dow (Monday=0..Sunday=6), is_holiday for each ISO8601
    timestamp (naive, local-to-the-dataset time as stored)."""
    rows = []
    for ts in timestamps:
        parsed = dt.datetime.fromisoformat(ts)
        rows.append({
            "timestamp": ts,
            "hour": parsed.hour,
            "dow": parsed.weekday(),
            "is_holiday": _is_us_federal_holiday(parsed.date()),
        })
    return rows


def build_feature_table(
    power_readings: List[dict],
    occupancy_rows: List[dict],
    weather_temperature: Dict[str, float],
    building_id: str,
    zone_id: Optional[str] = None,
) -> pd.DataFrame:
    """Left-joins occupancy/weather onto the power timestamp grid (power is
    the anchor series since forecasting targets power_kwh). Missing
    occupancy/weather at a given hour is left as NaN -- never filled with an
    invented value."""
    occupancy_hourly = resample_occupancy_to_hourly(occupancy_rows, zone_id) if zone_id else {}
    calendar_by_ts = {row["timestamp"]: row for row in build_calendar_features([r["ts"] for r in power_readings])}

    records = []
    for reading in power_readings:
        ts = reading["ts"]
        calendar = calendar_by_ts[ts]
        records.append({
            "timestamp": ts,
            "building_id": building_id,
            "zone_id": zone_id,
            "power_kwh": reading["kwh"],
            "occupancy": occupancy_hourly.get(ts, float("nan")),
            "hour": calendar["hour"],
            "dow": calendar["dow"],
            "is_holiday": calendar["is_holiday"],
            "temp": weather_temperature.get(ts, float("nan")),
        })

    return pd.DataFrame.from_records(
        records,
        columns=["timestamp", "building_id", "zone_id", "power_kwh", "occupancy", "hour", "dow", "is_holiday", "temp"],
    )
