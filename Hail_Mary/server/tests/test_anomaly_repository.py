"""Red-Green-Refactor: anomaly_event persistence + query/ack logic backing
GET /api/v1/anomaly and POST /api/v1/anomaly/{event_id}/ack. Real SQLite."""
import pytest

from Hail_Mary.server.db.connection import open_database
from Hail_Mary.server.api.anomaly import acknowledge_anomaly, insert_anomaly_events, query_anomalies


@pytest.fixture
def conn(tmp_path):
    connection = open_database(tmp_path / "hail_mary.db")
    yield connection
    connection.close()


def _events():
    return [
        {"event_id": "e1", "zone_id": "hall_main", "ts": "2026-09-09T09:00:00Z", "residual_kwh": 20.0, "occupancy_at_ts": 0, "severity": "high", "resolved": False},
        {"event_id": "e2", "zone_id": "hall_main", "ts": "2026-09-09T10:00:00Z", "residual_kwh": 5.0, "occupancy_at_ts": 0, "severity": "medium", "resolved": False},
    ]


def test_insert_and_query_all_anomalies(conn):
    inserted = insert_anomaly_events(conn, _events())
    assert inserted == 2

    rows = query_anomalies(conn)
    assert len(rows) == 2


def test_insert_anomaly_events_is_idempotent_by_event_id(conn):
    insert_anomaly_events(conn, _events())
    inserted_again = insert_anomaly_events(conn, _events())
    assert inserted_again == 0


def test_query_anomalies_filters_by_open_status(conn):
    insert_anomaly_events(conn, _events())
    acknowledge_anomaly(conn, "e1")

    open_events = query_anomalies(conn, status="open")
    resolved_events = query_anomalies(conn, status="resolved")

    assert [e["event_id"] for e in open_events] == ["e2"]
    assert [e["event_id"] for e in resolved_events] == ["e1"]


def test_acknowledge_anomaly_returns_false_for_unknown_event(conn):
    assert acknowledge_anomaly(conn, "does-not-exist") is False


def test_acknowledge_anomaly_marks_resolved(conn):
    insert_anomaly_events(conn, _events())

    result = acknowledge_anomaly(conn, "e1")

    assert result is True
    row = conn.execute("SELECT resolved FROM anomaly_event WHERE event_id='e1'").fetchone()
    assert row["resolved"] == 1
