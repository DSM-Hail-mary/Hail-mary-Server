"""Red-Green-Refactor: forecast persistence + query logic backing
GET /api/v1/forecast and GET /api/v1/forecast/ablation. Real SQLite, no
mocking."""
import pytest

from Hail_Mary.server.db.connection import open_database
from Hail_Mary.server.api.forecast import (
    insert_forecast_rows,
    query_forecast,
    query_forecast_rows_with_actual,
)


@pytest.fixture
def conn(tmp_path):
    connection = open_database(tmp_path / "hail_mary.db")
    yield connection
    connection.close()


def _rows():
    return [
        {"building_id": "b1", "target_ts": "2017-01-06T09:00:00", "with_occ_kwh": None, "without_occ_kwh": 20.0, "actual_kwh": 21.0},
        {"building_id": "b1", "target_ts": "2017-01-06T10:00:00", "with_occ_kwh": None, "without_occ_kwh": 22.0, "actual_kwh": 23.0},
    ]


def test_insert_and_query_forecast_round_trip(conn):
    inserted = insert_forecast_rows(conn, generated_at="2026-09-09T00:00:00Z", rows=_rows())
    assert inserted == 2

    rows = query_forecast(conn, building_id="b1")
    assert len(rows) == 2
    assert rows[0]["target_ts"] == "2017-01-06T09:00:00"
    assert rows[0]["without_occ_kwh"] == 20.0


def test_query_forecast_respects_horizon_limit(conn):
    insert_forecast_rows(conn, generated_at="2026-09-09T00:00:00Z", rows=_rows())

    rows = query_forecast(conn, building_id="b1", horizon=1)

    assert len(rows) == 1
    assert rows[0]["target_ts"] == "2017-01-06T09:00:00"


def test_query_forecast_only_returns_latest_generated_batch(conn):
    insert_forecast_rows(conn, generated_at="2026-09-09T00:00:00Z", rows=_rows())
    newer_rows = [{"building_id": "b1", "target_ts": "2017-01-06T09:00:00", "with_occ_kwh": None, "without_occ_kwh": 99.0, "actual_kwh": 21.0}]
    insert_forecast_rows(conn, generated_at="2026-09-09T01:00:00Z", rows=newer_rows)

    rows = query_forecast(conn, building_id="b1")

    assert len(rows) == 1
    assert rows[0]["without_occ_kwh"] == 99.0


def test_query_forecast_rows_with_actual_filters_by_building_and_period(conn):
    insert_forecast_rows(conn, generated_at="2026-09-09T00:00:00Z", rows=_rows())

    rows = query_forecast_rows_with_actual(conn, building_id="b1", period="2017-01-06")
    assert len(rows) == 2

    rows_wrong_period = query_forecast_rows_with_actual(conn, building_id="b1", period="2017-02")
    assert rows_wrong_period == []
