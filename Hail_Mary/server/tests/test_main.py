"""App-level concerns in main.py: CORS (code review 2026-09-14 -- Front is
its own repo/origin now, so cross-origin requests must be allowed) and the
custom RequestValidationError handler (sanitizes non-finite floats so a
rejected Infinity/NaN doesn't crash the 422 response itself)."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "hail_mary_test.db")
    return TestClient(app)


def test_cors_allows_a_cross_origin_get_request(client):
    # Simulates Front served from a different origin than this API (its
    # actual, current deployment shape -- see main.py's CORSMiddleware
    # comment). Browsers only send Origin on cross-origin requests; TestClient
    # lets us set it directly to exercise the same code path.
    response = client.get("/api/v1/occupancy/live", headers={"Origin": "http://localhost:8080"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_preflight_allows_post_with_custom_headers(client):
    # A real browser sends this OPTIONS preflight before POST /api/v1/occupancy
    # with a custom X-API-Key header (once a deployment sets HAIL_MARY_API_KEY).
    response = client.options(
        "/api/v1/occupancy",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_validation_error_response_is_valid_json_even_for_a_rejected_infinity(client):
    # Regression test for the exact bug the handler exists to prevent: before
    # it, FastAPI's default handler echoed the raw `inf` back in the error's
    # "input" field and crashed trying to json.dumps(..., allow_nan=False) it
    # -- turning a should-be-422 into an unhandled 500.
    payload_bytes = (
        b'[{"event_id": "e1", "zone_id": "z", "ts": "t", '
        b'"residual_kwh": Infinity, "occupancy_at_ts": 0, "severity": "high", "resolved": false}]'
    )

    response = client.post(
        "/api/v1/anomaly", content=payload_bytes, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    body = response.json()  # would raise if the response body weren't valid JSON
    assert body["detail"][0]["input"] == "inf"  # sanitized to a string, not the raw float
