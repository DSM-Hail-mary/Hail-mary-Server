"""Red-Green-Refactor: Feature Store (M4) -- aligns occupancy + public power
data + calendar/weather onto one hourly timestamp grid. Real BDG2 CSVs are
used for the power/weather inputs; occupancy inputs are small hand-built
fixtures with the exact schema Hail_Mary/edge/uplink.py emits (payload-schema
fixtures, not "mocking" -- no function/object is faked, only sample input
data is provided, same as every other test in this file)."""
from pathlib import Path

import math

from Hail_Mary.server.core.bdg2_loader import load_electricity_readings, load_weather_temperature
from Hail_Mary.server.core.feature_store import (
    build_calendar_features,
    build_feature_table,
    resample_occupancy_to_hourly,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "bdg2"
ELECTRICITY_CSV = DATA_DIR / "electricity_2017.csv"
WEATHER_CSV = DATA_DIR / "weather_panther_2017.csv"


def test_resample_occupancy_to_hourly_averages_minute_windows():
    rows = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 2},
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:01:00Z", "window_end": "2026-08-21T10:02:00Z", "count": 4},
        {"zone_id": "hall_main", "window_start": "2026-08-21T11:00:00Z", "window_end": "2026-08-21T11:01:00Z", "count": 10},
        {"zone_id": "other_zone", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 99},
    ]

    hourly = resample_occupancy_to_hourly(rows, zone_id="hall_main")

    assert hourly["2026-08-21T10:00:00"] == 3.0  # mean(2, 4)
    assert hourly["2026-08-21T11:00:00"] == 10.0
    assert "other_zone" not in str(hourly)


def test_build_calendar_features_hour_dow_and_known_us_holiday():
    # 2017-07-04 is a real, historical US Independence Day (Tuesday).
    rows = build_calendar_features(["2017-07-04T10:00:00", "2017-07-05T10:00:00"])

    assert rows[0] == {"timestamp": "2017-07-04T10:00:00", "hour": 10, "dow": 1, "is_holiday": True}
    assert rows[1] == {"timestamp": "2017-07-05T10:00:00", "hour": 10, "dow": 2, "is_holiday": False}


def test_build_calendar_features_new_years_day_2017():
    # 2017-01-01 is a real Sunday and a US federal holiday.
    rows = build_calendar_features(["2017-01-01T00:00:00"])
    assert rows[0]["dow"] == 6  # Sunday
    assert rows[0]["is_holiday"] is True


def test_build_feature_table_joins_real_power_weather_and_given_occupancy():
    power = load_electricity_readings(ELECTRICITY_CSV, "Panther_office_Karla")[:3]
    weather = load_weather_temperature(WEATHER_CSV)
    occupancy_rows = [
        {"zone_id": "z1", "window_start": "2017-01-01T00:00:00", "window_end": "2017-01-01T00:01:00", "count": 5},
    ]

    table = build_feature_table(
        power_readings=power,
        occupancy_rows=occupancy_rows,
        weather_temperature=weather,
        building_id="Panther_office_Karla",
        zone_id="z1",
    )

    assert list(table.columns) == [
        "timestamp", "building_id", "zone_id", "power_kwh", "occupancy", "hour", "dow", "is_holiday", "temp",
    ]
    assert len(table) == 3
    first = table.iloc[0]
    assert first["timestamp"] == "2017-01-01T00:00:00"
    assert first["power_kwh"] == 18.1235
    assert first["temp"] == 15.6
    assert first["occupancy"] == 5.0
    assert first["hour"] == 0
    assert first["is_holiday"] == True  # noqa: E712  (real 2017 New Year's Day)

    second = table.iloc[1]
    # No occupancy fixture given for 01:00 -> honestly absent, not fabricated.
    assert math.isnan(second["occupancy"])


def test_build_feature_table_without_any_occupancy_data_leaves_column_nan():
    power = load_electricity_readings(ELECTRICITY_CSV, "Panther_office_Karla")[:5]
    weather = load_weather_temperature(WEATHER_CSV)

    table = build_feature_table(
        power_readings=power,
        occupancy_rows=[],
        weather_temperature=weather,
        building_id="Panther_office_Karla",
        zone_id="z1",
    )

    assert table["occupancy"].isna().all()
    assert not table["power_kwh"].isna().any()
