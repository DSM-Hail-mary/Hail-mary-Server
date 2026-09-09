"""Loader for the Building Data Genome Project 2 (BDG2) subset used by
Hail-Mary (component 4 -- 실제 데이터셋 확보).

Source: https://github.com/buds-lab/building-data-genome-project-2 (public,
no auth). Trimmed locally to 3 real Panther-site office buildings / year 2017
(see Hail_Mary/server/data/raw/bdg2/SOURCE.txt for exactly how). This module
only reads the trimmed CSVs -- it never invents a value: a blank cell in the
source CSV is skipped, not backfilled.
"""
import csv
import sqlite3
from pathlib import Path
from typing import Dict, List, Union

BDG2_BUILDING_IDS = (
    "Panther_office_Karla",
    "Panther_office_Catherine",
    "Panther_office_Ruthie",
)


def _to_iso(ts: str) -> str:
    """'2017-01-01 00:00:00' -> '2017-01-01T00:00:00' (ISO8601, matches the
    occupancy payload's timestamp format from Hail_Mary/edge/uplink.py)."""
    return ts.replace(" ", "T")


def load_electricity_readings(csv_path: Union[str, Path], building_id: str) -> List[dict]:
    """Read one building's hourly electricity column from the trimmed BDG2
    CSV. Rows with a blank reading (real sensor/reporting gaps) are skipped."""
    readings = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if building_id not in reader.fieldnames:
            raise KeyError(f"{building_id!r} is not a column in {csv_path}")
        for row in reader:
            value = row[building_id]
            if value == "":
                continue
            readings.append({"ts": _to_iso(row["timestamp"]), "kwh": float(value)})
    return readings


def load_weather_temperature(csv_path: Union[str, Path]) -> Dict[str, float]:
    """Read the real airTemperature column, keyed by ISO8601 timestamp."""
    temps = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            value = row["airTemperature"]
            if value == "":
                continue
            temps[_to_iso(row["timestamp"])] = float(value)
    return temps


def ingest_bdg2_into_db(
    conn: sqlite3.Connection,
    electricity_csv_path: Union[str, Path],
    building_ids=BDG2_BUILDING_IDS,
) -> Dict[str, int]:
    """Load each building's real electricity series into the power_reading
    table. Idempotent (UNIQUE(building_id, ts) + INSERT OR IGNORE) so it can
    be re-run safely. Returns {building_id: rows newly inserted}."""
    inserted_counts = {}
    for building_id in building_ids:
        readings = load_electricity_readings(electricity_csv_path, building_id)
        inserted = 0
        for reading in readings:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO power_reading (building_id, ts, kwh) VALUES (?, ?, ?)",
                (building_id, reading["ts"], reading["kwh"]),
            )
            inserted += cursor.rowcount
        inserted_counts[building_id] = inserted
    conn.commit()
    return inserted_counts
