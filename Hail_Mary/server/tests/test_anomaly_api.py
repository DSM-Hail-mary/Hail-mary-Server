"""HTTP-level tests for GET /api/v1/anomaly and POST /api/v1/anomaly/{id}/ack
against a real FastAPI app + real (tmp) SQLite DB via TestClient."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.api.anomaly import insert_anomaly_events
from Hail_Mary.server.main import create_app


@pytest.fixture
def app_and_client(tmp_path):
    app = create_app(tmp_path / "hail_mary_test.db")
    return app, TestClient(app)


def _seed(app):
    insert_anomaly_events(app.state.db, [
        {"event_id": "e1", "zone_id": "hall_main", "ts": "2026-09-09T09:00:00Z", "residual_kwh": 20.0, "occupancy_at_ts": 0, "severity": "high", "resolved": False},
    ])


def test_get_anomalies_returns_seeded_event(app_and_client):
    app, client = app_and_client
    _seed(app)

    response = client.get("/api/v1/anomaly")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event_id"] == "e1"
    assert body[0]["resolved"] == 0


def test_get_anomalies_filters_open_status(app_and_client):
    app, client = app_and_client
    _seed(app)

    response = client.get("/api/v1/anomaly", params={"status": "open"})
    assert len(response.json()) == 1

    client.post("/api/v1/anomaly/e1/ack")
    response = client.get("/api/v1/anomaly", params={"status": "open"})
    assert response.json() == []


def test_ack_unknown_event_returns_404(app_and_client):
    _, client = app_and_client
    response = client.post("/api/v1/anomaly/does-not-exist/ack")
    assert response.status_code == 404


def test_ack_known_event_marks_resolved(app_and_client):
    app, client = app_and_client
    _seed(app)

    response = client.post("/api/v1/anomaly/e1/ack")

    assert response.status_code == 200
    assert response.json() == {"event_id": "e1", "resolved": True}
