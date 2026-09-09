"""Red-Green-Refactor: BDG2 public-dataset loader (component 4 -- real data,
downloaded from https://github.com/buds-lab/building-data-genome-project-2,
trimmed to 3 Panther-site office buildings / year 2017, see
Hail_Mary/server/data/raw/bdg2/SOURCE.txt for provenance). No synthetic values:
missing readings in the source CSV are skipped, never invented.
"""
from pathlib import Path

import pytest

from Hail_Mary.server.core.bdg2_loader import (
    BDG2_BUILDING_IDS,
    ingest_bdg2_into_db,
    load_electricity_readings,
    load_weather_temperature,
)
from Hail_Mary.server.db.connection import open_database

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "bdg2"
ELECTRICITY_CSV = DATA_DIR / "electricity_2017.csv"
WEATHER_CSV = DATA_DIR / "weather_panther_2017.csv"


def test_bdg2_raw_files_exist():
    assert ELECTRICITY_CSV.exists()
    assert WEATHER_CSV.exists()


def test_load_electricity_readings_matches_real_first_row():
    readings = load_electricity_readings(ELECTRICITY_CSV, "Panther_office_Karla")

    assert readings[0] == {"ts": "2017-01-01T00:00:00", "kwh": 18.1235}
    assert len(readings) > 8000  # ~8760 hourly rows in 2017, minus real gaps


def test_load_electricity_readings_skips_missing_values_without_fabricating():
    readings = load_electricity_readings(ELECTRICITY_CSV, "Panther_office_Karla")
    timestamps = {r["ts"] for r in readings}
    # 2017 has ~11 real missing hours for Karla (verified against the raw CSV);
    # the loader must skip them, not backfill with 0/interpolated values.
    assert len(readings) < 8760

    for r in readings:
        assert isinstance(r["kwh"], float)


def test_load_electricity_readings_unknown_building_raises():
    with pytest.raises(KeyError):
        load_electricity_readings(ELECTRICITY_CSV, "not_a_real_building")


def test_load_weather_temperature_matches_real_first_row():
    temps = load_weather_temperature(WEATHER_CSV)

    assert temps["2017-01-01T00:00:00"] == 15.6
    assert temps["2017-01-01T03:00:00"] == 13.3
    assert len(temps) == 8760


def test_ingest_bdg2_into_db_populates_power_reading_for_all_selected_buildings(tmp_path):
    conn = open_database(tmp_path / "hail_mary.db")

    counts = ingest_bdg2_into_db(conn, ELECTRICITY_CSV)

    assert set(counts) == set(BDG2_BUILDING_IDS)
    total_in_db = conn.execute("SELECT COUNT(*) AS n FROM power_reading").fetchone()["n"]
    assert total_in_db == sum(counts.values())
    row = conn.execute(
        "SELECT kwh FROM power_reading WHERE building_id=? AND ts=?",
        ("Panther_office_Karla", "2017-01-01T00:00:00"),
    ).fetchone()
    assert row["kwh"] == 18.1235
    conn.close()


def test_ingest_bdg2_into_db_is_idempotent(tmp_path):
    conn = open_database(tmp_path / "hail_mary.db")
    ingest_bdg2_into_db(conn, ELECTRICITY_CSV)

    counts_again = ingest_bdg2_into_db(conn, ELECTRICITY_CSV)

    assert sum(counts_again.values()) == 0  # nothing new inserted on re-run
    conn.close()
