"""HTTP-level tests for POST/GET /api/v1/savings against a real FastAPI app +
real (tmp) SQLite DB via TestClient."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.main import create_app


@pytest.fixture
def app_and_client(tmp_path):
    app = create_app(tmp_path / "hail_mary_test.db")
    return app, TestClient(app)


def test_post_savings_computes_and_persists(app_and_client):
    _, client = app_and_client

    response = client.post("/api/v1/savings", json={
        "period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-08T00:00:00Z",
        "actual_kwh": [100.0, 100.0], "simulated_kwh": [80.0, 80.0],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["saved_kwh"] == 40.0
    assert body["saved_pct"] == 20.0

    listing = client.get("/api/v1/savings").json()
    assert len(listing) == 1
    assert listing[0]["saved_kwh"] == 40.0


def test_post_savings_rejects_mismatched_series(app_and_client):
    _, client = app_and_client

    response = client.post("/api/v1/savings", json={
        "period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-08T00:00:00Z",
        "actual_kwh": [100.0, 100.0], "simulated_kwh": [80.0],
    })

    assert response.status_code == 422


def test_post_savings_rejects_empty_series(app_and_client):
    _, client = app_and_client

    response = client.post("/api/v1/savings", json={
        "period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-08T00:00:00Z",
        "actual_kwh": [], "simulated_kwh": [],
    })

    assert response.status_code == 422


def test_post_savings_rejects_infinite_values_in_either_series(app_and_client):
    # Same class of bug as POST /api/v1/anomaly's residual_kwh (code review
    # 2026-09-14): an unconstrained float list accepts the JSON literal
    # "Infinity", which would otherwise reach core.savings.compute_savings()
    # and produce a non-finite saved_kwh/saved_pct that crashes on response
    # serialization instead of failing 422 cleanly.
    _, client = app_and_client
    payload_bytes = (
        b'{"period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-08T00:00:00Z", '
        b'"actual_kwh": [Infinity], "simulated_kwh": [80.0]}'
    )

    response = client.post("/api/v1/savings", content=payload_bytes, headers={"Content-Type": "application/json"})

    assert response.status_code == 422


def test_get_savings_filters_by_period_start(app_and_client):
    _, client = app_and_client
    client.post("/api/v1/savings", json={
        "period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-08T00:00:00Z",
        "actual_kwh": [10.0], "simulated_kwh": [8.0],
    })
    client.post("/api/v1/savings", json={
        "period_start": "2026-09-08T00:00:00Z", "period_end": "2026-09-15T00:00:00Z",
        "actual_kwh": [10.0], "simulated_kwh": [9.0],
    })

    response = client.get("/api/v1/savings", params={"period_start": "2026-09-08T00:00:00Z"})

    assert len(response.json()) == 1
    assert response.json()[0]["period_start"] == "2026-09-08T00:00:00Z"


def test_get_savings_empty_when_no_reports(app_and_client):
    _, client = app_and_client
    assert client.get("/api/v1/savings").json() == []
