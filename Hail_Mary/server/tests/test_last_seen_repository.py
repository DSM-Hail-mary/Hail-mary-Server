"""Red-Green-Refactor: last-seen-image persistence logic (zone_id validation,
disk write + DB upsert, listing). Pure functions against a real SQLite
connection and a real tmp_path directory -- no mocking.
"""
import pytest

from Hail_Mary.server.db.connection import open_database
from Hail_Mary.server.api.last_seen import (
    image_path_for,
    is_valid_zone_id,
    list_last_seen,
    save_last_seen_image,
)

_TINY_JPEG = b"\xff\xd8\xff\xe0not a real jpeg but real bytes\xff\xd9"


@pytest.fixture
def conn(tmp_path):
    connection = open_database(tmp_path / "hail_mary.db")
    yield connection
    connection.close()


@pytest.fixture
def image_dir(tmp_path):
    return tmp_path / "last_seen"


def test_is_valid_zone_id_accepts_alnum_underscore():
    assert is_valid_zone_id("hall_main") is True
    assert is_valid_zone_id("zone1") is True


@pytest.mark.parametrize("zone_id", ["", "..", "../etc", "a/b", "a\\b", "..\\..\\evil"])
def test_is_valid_zone_id_rejects_path_traversal(zone_id):
    assert is_valid_zone_id(zone_id) is False


def test_save_last_seen_image_writes_file_and_upserts_row(conn, image_dir):
    save_last_seen_image(conn, "hall_main", _TINY_JPEG, "2026-09-09T10:00:00.000000Z", image_dir)

    path = image_path_for("hall_main", image_dir)
    assert path.is_file()
    assert path.read_bytes() == _TINY_JPEG

    row = conn.execute(
        "SELECT zone_id, captured_at, image_path FROM last_seen_image WHERE zone_id = ?",
        ("hall_main",),
    ).fetchone()
    assert row["zone_id"] == "hall_main"
    assert row["captured_at"] == "2026-09-09T10:00:00.000000Z"
    assert row["image_path"] == str(path)


def test_save_last_seen_image_replaces_previous_image_for_same_zone(conn, image_dir):
    save_last_seen_image(conn, "hall_main", b"first-bytes", "2026-09-09T10:00:00.000000Z", image_dir)
    save_last_seen_image(conn, "hall_main", b"second-bytes", "2026-09-09T10:05:00.000000Z", image_dir)

    total = conn.execute("SELECT COUNT(*) AS n FROM last_seen_image").fetchone()["n"]
    assert total == 1

    path = image_path_for("hall_main", image_dir)
    assert path.read_bytes() == b"second-bytes"

    row = conn.execute(
        "SELECT captured_at FROM last_seen_image WHERE zone_id = ?", ("hall_main",)
    ).fetchone()
    assert row["captured_at"] == "2026-09-09T10:05:00.000000Z"


def test_list_last_seen_returns_all_zones(conn, image_dir):
    save_last_seen_image(conn, "hall_main", _TINY_JPEG, "2026-09-09T10:00:00.000000Z", image_dir)
    save_last_seen_image(conn, "hall_side", _TINY_JPEG, "2026-09-09T10:01:00.000000Z", image_dir)

    results = list_last_seen(conn)

    by_zone = {row["zone_id"]: row["captured_at"] for row in results}
    assert by_zone == {
        "hall_main": "2026-09-09T10:00:00.000000Z",
        "hall_side": "2026-09-09T10:01:00.000000Z",
    }


def test_list_last_seen_returns_empty_list_when_no_data(conn):
    assert list_last_seen(conn) == []


def test_last_seen_image_insert_or_replace_keeps_single_row_per_zone(conn):
    conn.execute(
        "INSERT OR REPLACE INTO last_seen_image (zone_id, captured_at, image_path) VALUES (?, ?, ?)",
        ("hall_main", "2026-09-09T10:00:00.000000Z", "/tmp/a.jpg"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO last_seen_image (zone_id, captured_at, image_path) VALUES (?, ?, ?)",
        ("hall_main", "2026-09-09T10:05:00.000000Z", "/tmp/b.jpg"),
    )
    conn.commit()

    rows = conn.execute("SELECT * FROM last_seen_image WHERE zone_id = ?", ("hall_main",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["image_path"] == "/tmp/b.jpg"
