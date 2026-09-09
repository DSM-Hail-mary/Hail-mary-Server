"""HTTP-level tests for GET /api/v1/forecast and GET /api/v1/forecast/ablation
against a real FastAPI app + real (tmp) SQLite DB via TestClient."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.api.forecast import insert_forecast_rows
from Hail_Mary.server.main import create_app


@pytest.fixture
def app_and_client(tmp_path):
    app = create_app(tmp_path / "hail_mary_test.db")
    return app, TestClient(app)


def test_get_forecast_returns_stored_rows(app_and_client):
    app, client = app_and_client
    insert_forecast_rows(app.state.db, generated_at="2026-09-09T00:00:00Z", rows=[
        {"building_id": "b1", "target_ts": "2017-01-06T09:00:00", "with_occ_kwh": None, "without_occ_kwh": 20.0, "actual_kwh": None},
    ])

    response = client.get("/api/v1/forecast", params={"building_id": "b1"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["without_occ_kwh"] == 20.0


def test_get_forecast_unknown_building_returns_empty_list(app_and_client):
    _, client = app_and_client
    response = client.get("/api/v1/forecast", params={"building_id": "nope"})
    assert response.status_code == 200
    assert response.json() == []


def test_get_forecast_ablation_computes_metrics_from_stored_rows(app_and_client):
    app, client = app_and_client
    insert_forecast_rows(app.state.db, generated_at="2026-09-09T00:00:00Z", rows=[
        {"building_id": "b1", "target_ts": "2017-01-06T09:00:00", "with_occ_kwh": None, "without_occ_kwh": 18.0, "actual_kwh": 20.0},
        {"building_id": "b1", "target_ts": "2017-01-06T10:00:00", "with_occ_kwh": None, "without_occ_kwh": 24.0, "actual_kwh": 20.0},
    ])

    response = client.get("/api/v1/forecast/ablation", params={"building_id": "b1"})

    assert response.status_code == 200
    body = response.json()
    assert body["n"] == 2
    assert body["without_occ_mae"] == 3.0
    assert body["with_occ_mae"] is None
