"""Red-Green-Refactor: occupancy persistence/query logic (M2/M3 edge -> server
ingestion, and the "current occupancy" read used by /api/v1/occupancy/live).

Pure functions against a real SQLite connection -- no mocking.
"""
import pytest

from Hail_Mary.server.db.connection import open_database
from Hail_Mary.server.api.occupancy import insert_occupancy_batch, latest_occupancy


@pytest.fixture
def conn(tmp_path):
    connection = open_database(tmp_path / "hail_mary.db")
    yield connection
    connection.close()


def _batch():
    return [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3},
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:01:00Z", "window_end": "2026-08-21T10:02:00Z", "count": 5},
        {"zone_id": "hall_side", "window_start": "2026-08-21T10:01:00Z", "window_end": "2026-08-21T10:02:00Z", "count": 1},
    ]


def test_insert_occupancy_batch_persists_all_rows(conn):
    inserted = insert_occupancy_batch(conn, _batch())

    assert inserted == 3
    total = conn.execute("SELECT COUNT(*) AS n FROM occupancy").fetchone()["n"]
    assert total == 3


def test_insert_occupancy_batch_is_idempotent_on_retry(conn):
    insert_occupancy_batch(conn, _batch())
    # Simulate the edge retrying the same HTTP batch after a lost ack.
    inserted_again = insert_occupancy_batch(conn, _batch())

    assert inserted_again == 0
    total = conn.execute("SELECT COUNT(*) AS n FROM occupancy").fetchone()["n"]
    assert total == 3


def test_insert_occupancy_batch_rejects_empty_zone_id(conn):
    bad = [{"zone_id": "", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 3}]
    with pytest.raises(ValueError):
        insert_occupancy_batch(conn, bad)


def test_insert_occupancy_batch_rejects_negative_count(conn):
    bad = [{"zone_id": "z1", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": -1}]
    with pytest.raises(ValueError):
        insert_occupancy_batch(conn, bad)


def test_latest_occupancy_returns_most_recent_window_per_zone(conn):
    insert_occupancy_batch(conn, _batch())

    result = latest_occupancy(conn, zone_id="hall_main")

    assert result == {
        "zone_id": "hall_main",
        "window_start": "2026-08-21T10:01:00Z",
        "window_end": "2026-08-21T10:02:00Z",
        "count": 5,
    }


def test_latest_occupancy_returns_none_for_unknown_zone(conn):
    insert_occupancy_batch(conn, _batch())

    assert latest_occupancy(conn, zone_id="nonexistent") is None


def test_latest_occupancy_without_zone_id_returns_all_zones_latest(conn):
    insert_occupancy_batch(conn, _batch())

    results = latest_occupancy(conn, zone_id=None)

    by_zone = {row["zone_id"]: row["count"] for row in results}
    assert by_zone == {"hall_main": 5, "hall_side": 1}
