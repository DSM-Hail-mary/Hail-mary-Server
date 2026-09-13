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


def test_post_anomaly_batch_persists_and_is_queryable(app_and_client):
    # Code review 2026-09-13: core.anomaly_detector.detect_anomalies()
    # produces exactly this event shape, but there was no HTTP route to feed
    # its output in -- insert_anomaly_events() was only ever called from
    # this file's own tests. This is the ingestion counterpart to
    # POST /api/v1/occupancy (which does the same job for M2/M3 uplink).
    _, client = app_and_client
    payload = [
        {"event_id": "e-new", "zone_id": "hall_main", "ts": "2026-09-13T09:00:00Z",
         "residual_kwh": 12.5, "occupancy_at_ts": 0, "severity": "high", "resolved": False},
    ]

    response = client.post("/api/v1/anomaly", json=payload)

    assert response.status_code == 200
    assert response.json() == {"inserted": 1, "received": 1}

    listed = client.get("/api/v1/anomaly").json()
    assert len(listed) == 1
    assert listed[0]["event_id"] == "e-new"


def test_post_anomaly_batch_retry_is_idempotent(app_and_client):
    _, client = app_and_client
    payload = [
        {"event_id": "e-dup", "zone_id": "hall_main", "ts": "2026-09-13T09:00:00Z",
         "residual_kwh": 12.5, "occupancy_at_ts": 0, "severity": "high", "resolved": False},
    ]
    client.post("/api/v1/anomaly", json=payload)

    response = client.post("/api/v1/anomaly", json=payload)

    assert response.status_code == 200
    assert response.json() == {"inserted": 0, "received": 1}


def test_post_anomaly_batch_rejects_infinite_residual_kwh(app_and_client):
    # Code review 2026-09-14: residual_kwh had no allow_inf_nan=False, so a
    # POST with "residual_kwh": Infinity (a legal IEEE-754 double, and
    # json.loads() accepts the literal "Infinity"/"NaN" by default) inserted
    # successfully, then permanently 500'd every subsequent GET /api/v1/anomaly
    # for everyone -- Starlette's JSONResponse.render() calls
    # json.dumps(..., allow_nan=False), which raises ValueError on an inf/nan
    # float with no exception handler anywhere to catch it. There was no way
    # to recover except editing the SQLite file directly (ack only resolves,
    # never deletes). Must be rejected at the ingestion boundary instead.
    _, client = app_and_client
    payload_bytes = (
        b'[{"event_id": "e-inf", "zone_id": "hall_main", "ts": "2026-09-13T09:00:00Z", '
        b'"residual_kwh": Infinity, "occupancy_at_ts": 0, "severity": "high", "resolved": false}]'
    )

    response = client.post(
        "/api/v1/anomaly", content=payload_bytes, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422

    # The list endpoint must still work -- nothing got through to break it.
    listed = client.get("/api/v1/anomaly")
    assert listed.status_code == 200
    assert listed.json() == []


def test_post_anomaly_batch_rejects_empty_event_id(app_and_client):
    _, client = app_and_client
    payload = [
        {"event_id": "", "zone_id": "hall_main", "ts": "2026-09-13T09:00:00Z",
         "residual_kwh": 12.5, "occupancy_at_ts": 0, "severity": "high", "resolved": False},
    ]

    response = client.post("/api/v1/anomaly", json=payload)

    assert response.status_code == 422  # pydantic Field(min_length=1) validation


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
