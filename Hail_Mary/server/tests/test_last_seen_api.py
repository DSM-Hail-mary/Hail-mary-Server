"""HTTP-level tests for POST/GET /api/v1/last-seen against a real FastAPI app
instance + real (tmp) SQLite DB via TestClient. Uploads use TestClient's real
multipart/form-data encoding -- no mocking."""
import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.main import create_app

_TINY_JPEG = b"\xff\xd8\xff\xe0not a real jpeg but real bytes\xff\xd9"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the module-level IMAGE_DIR at a per-test tmp dir so tests don't
    # collide with each other or with the on-disk demo data directory.
    from Hail_Mary.server.api import last_seen

    monkeypatch.setattr(last_seen, "IMAGE_DIR", tmp_path / "last_seen_images")
    app = create_app(tmp_path / "hail_mary_test.db")
    return TestClient(app)


def _upload(client, zone_id, image_bytes=_TINY_JPEG, filename="frame.jpg"):
    return client.post(
        f"/api/v1/last-seen/{zone_id}",
        files={"image": (filename, image_bytes, "image/jpeg")},
    )


def test_post_last_seen_image_returns_zone_id_and_captured_at(client):
    response = _upload(client, "hall_main")

    assert response.status_code == 200
    body = response.json()
    assert body["zone_id"] == "hall_main"
    assert body["captured_at"]  # non-empty ISO8601 UTC string


def test_post_last_seen_image_rejects_path_traversal_zone_id(client):
    response = client.post(
        "/api/v1/last-seen/..%5C..%5Cevil",
        files={"image": ("frame.jpg", _TINY_JPEG, "image/jpeg")},
    )

    assert response.status_code == 400


def test_get_last_seen_list_is_empty_when_no_uploads(client):
    response = client.get("/api/v1/last-seen")

    assert response.status_code == 200
    assert response.json() == []


def test_get_last_seen_list_returns_uploaded_zones(client):
    _upload(client, "hall_main")
    _upload(client, "hall_side")

    response = client.get("/api/v1/last-seen")

    assert response.status_code == 200
    body = response.json()
    by_zone = {row["zone_id"]: row for row in body}
    assert set(by_zone) == {"hall_main", "hall_side"}
    assert by_zone["hall_main"]["image_url"] == "/api/v1/last-seen/hall_main/image"
    assert by_zone["hall_main"]["captured_at"]


def test_get_last_seen_list_reflects_replacement_not_history(client):
    _upload(client, "hall_main", image_bytes=b"first")
    _upload(client, "hall_main", image_bytes=b"second")

    response = client.get("/api/v1/last-seen")

    body = response.json()
    assert len(body) == 1


def test_get_last_seen_image_roundtrips_exact_bytes(client):
    _upload(client, "hall_main", image_bytes=_TINY_JPEG)

    response = client.get("/api/v1/last-seen/hall_main/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == _TINY_JPEG


def test_get_last_seen_image_replaced_by_second_upload(client):
    _upload(client, "hall_main", image_bytes=b"first-bytes")
    _upload(client, "hall_main", image_bytes=b"second-bytes")

    response = client.get("/api/v1/last-seen/hall_main/image")

    assert response.content == b"second-bytes"


def test_get_last_seen_image_returns_404_for_unknown_zone(client):
    response = client.get("/api/v1/last-seen/nope/image")

    assert response.status_code == 404


def test_get_last_seen_image_rejects_path_traversal_zone_id(client):
    response = client.get("/api/v1/last-seen/..%5C..%5Cevil/image")

    assert response.status_code == 400
