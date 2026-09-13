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


def test_latest_occupancy_breaks_window_end_ties_by_most_recently_inserted(conn):
    # Two rows for the same zone can legitimately share window_end (e.g. a
    # 1-minute window re-reported by two overlapping aggregator runs). Before
    # the fix, both the single-zone and all-zones queries had no deterministic
    # tie-break, so SQLite could return either row depending on its internal
    # b-tree state -- see code review 2026-09-11. The most-recently-inserted
    # row (highest autoincrement id) should win consistently.
    tie_batch = [
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:00Z", "window_end": "2026-08-21T10:01:00Z", "count": 2},
        {"zone_id": "hall_main", "window_start": "2026-08-21T10:00:30Z", "window_end": "2026-08-21T10:01:00Z", "count": 9},
    ]
    insert_occupancy_batch(conn, tie_batch)

    single = latest_occupancy(conn, zone_id="hall_main")
    assert single["count"] == 9

    all_zones = latest_occupancy(conn, zone_id=None)
    assert all_zones[0]["count"] == 9


def test_latest_occupancy_queries_use_the_zone_index_not_a_temp_sort(conn):
    # Code review 2026-09-13: neither query had index support, so SQLite
    # built a temp b-tree to sort by window_end for every zone lookup (an
    # O(rows-for-that-zone log rows-for-that-zone) cost paid on every call,
    # for the endpoint the live dashboard polls most frequently). Verified
    # (see also idx_occupancy_zone_latest in schema.py) that after adding
    # the index, both branches resolve "latest row for a zone" via a direct
    # indexed SEARCH instead of a sort -- "USE TEMP B-TREE FOR ORDER BY"
    # must not appear in either plan. (The all-zones query still SCANs the
    # outer table once -- one row touched per historical record is
    # unavoidable with this "per-row correlated lookup" shape -- but each of
    # those per-row lookups is now an index SEARCH, not a re-sort.)
    insert_occupancy_batch(conn, _batch())

    single_plan = conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT zone_id, window_start, window_end, count FROM occupancy "
        "WHERE zone_id = ? ORDER BY window_end DESC, id DESC LIMIT 1",
        ("hall_main",),
    ).fetchall()
    all_zones_plan = conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT zone_id, window_start, window_end, count FROM occupancy o "
        "WHERE id = ("
        "  SELECT id FROM occupancy WHERE zone_id = o.zone_id "
        "  ORDER BY window_end DESC, id DESC LIMIT 1"
        ") "
        "ORDER BY zone_id ASC"
    ).fetchall()

    for plan in (single_plan, all_zones_plan):
        detail = " ".join(row[3] for row in plan)
        assert "idx_occupancy_zone_latest" in detail, detail
        assert "TEMP B-TREE" not in detail, detail
