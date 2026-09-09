"""HTTP-level tests for POST /api/v1/occupancy and GET /api/v1/occupancy/live,
against a real FastAPI app instance + real (tmp) SQLite DB via TestClient.
No mocking -- this is a real app processing real HTTP requests."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "hail_mary_test.db")
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_occupancy_batch_matches_edge_uplink_payload_shape(client):
    # Same shape as Hail_Mary/edge/uplink.py build_occupancy_payload() output.
    payload = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3},
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:01:00Z", "window_end": "2026-08-21T10:02:00Z", "count": 5},
    ]

    response = client.post("/api/v1/occupancy", json=payload)

    assert response.status_code == 200
    assert response.json() == {"inserted": 2, "received": 2}


def test_post_occupancy_batch_retry_is_idempotent(client):
    payload = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3},
    ]
    client.post("/api/v1/occupancy", json=payload)

    response = client.post("/api/v1/occupancy", json=payload)

    assert response.status_code == 200
    assert response.json() == {"inserted": 0, "received": 1}


def test_post_occupancy_batch_rejects_negative_count(client):
    payload = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": -1},
    ]

    response = client.post("/api/v1/occupancy", json=payload)

    assert response.status_code == 422  # pydantic Field(ge=0) validation


def test_get_live_occupancy_for_known_zone(client):
    payload = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3},
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:01:00Z", "window_end": "2026-08-21T10:02:00Z", "count": 5},
    ]
    client.post("/api/v1/occupancy", json=payload)

    response = client.get("/api/v1/occupancy/live", params={"zone_id": "hall_main"})

    assert response.status_code == 200
    assert response.json()["count"] == 5


def test_get_live_occupancy_for_unknown_zone_returns_null(client):
    response = client.get("/api/v1/occupancy/live", params={"zone_id": "nope"})

    assert response.status_code == 200
    assert response.json() is None


def test_get_live_occupancy_without_zone_id_returns_all_zones(client):
    payload = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3},
        {"zone_id": "hall_side", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 1},
    ]
    client.post("/api/v1/occupancy", json=payload)

    response = client.get("/api/v1/occupancy/live")

    assert response.status_code == 200
    by_zone = {row["zone_id"]: row["count"] for row in response.json()}
    assert by_zone == {"hall_main": 3, "hall_side": 1}
