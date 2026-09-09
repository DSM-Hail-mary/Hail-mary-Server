"""Red-Green-Refactor: savings_report persistence/query backing
POST /api/v1/savings and GET /api/v1/savings. Real SQLite."""
import pytest

from Hail_Mary.server.api.savings import insert_savings_report, query_savings_reports
from Hail_Mary.server.db.connection import open_database


@pytest.fixture
def conn(tmp_path):
    connection = open_database(tmp_path / "hail_mary.db")
    yield connection
    connection.close()


def _report(period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z"):
    return {
        "period_start": period_start, "period_end": period_end,
        "saved_kwh": 12.5, "saved_pct": 8.0, "co2_kg": 5.9, "tree_equivalent": 0.9,
    }


def test_insert_and_query_all_reports(conn):
    insert_savings_report(conn, _report())

    rows = query_savings_reports(conn)

    assert len(rows) == 1
    assert rows[0]["saved_kwh"] == 12.5


def test_insert_is_idempotent_by_period(conn):
    insert_savings_report(conn, _report())
    insert_savings_report(conn, _report())

    assert len(query_savings_reports(conn)) == 1


def test_query_filters_by_period_start(conn):
    insert_savings_report(conn, _report(period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z"))
    insert_savings_report(conn, _report(period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z"))

    rows = query_savings_reports(conn, period_start="2026-09-08T00:00:00Z")

    assert len(rows) == 1
    assert rows[0]["period_start"] == "2026-09-08T00:00:00Z"
