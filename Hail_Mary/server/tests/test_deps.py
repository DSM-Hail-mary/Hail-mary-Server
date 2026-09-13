"""Regression tests for DB-access concurrency safety (api.deps.get_db).

History: the original shared sqlite3.Connection had no synchronization at
all (2026-09-11 review) -- concurrent requests corrupted data. The first fix
added a process-wide threading.Lock held around each request's DB use
(2026-09-11 fix). That introduced a NEW bug (2026-09-13 review): FastAPI
dispatches both dependency resolution and each sync route body (or an
explicit run_in_threadpool call, as in last_seen.py's async upload route)
through the same shared anyio worker-thread pool (default capacity 40).
Holding db_lock across that dispatch boundary meant enough concurrent
requests could permanently starve the pool: every thread ends up blocked
waiting to acquire the lock, with no thread left free to run the one
request that's actually holding it -- a real deadlock, not just slowness.

Fix: no process-wide lock at all. get_db() opens a brand-new sqlite3
connection scoped to exactly one request, so no connection object is ever
touched by more than one thread at a time (it's never shared between
concurrent requests, only ever used by whichever single request opened it).
SQLite's own file-level locking (with connect(..., timeout=...) as the
busy-retry window) already handles concurrent writers safely -- no
Python-level lock is needed to prevent corruption, and with no cross-request
coordination there is no deadlock class to begin with.
"""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from Hail_Mary.server.api.deps import get_db
from Hail_Mary.server.db.connection import open_database
from Hail_Mary.server.main import create_app


class _FakeState:
    def __init__(self, db_path):
        self.db_path = db_path


class _FakeApp:
    def __init__(self, db_path):
        self.state = _FakeState(db_path)


class _FakeRequest:
    def __init__(self, app):
        self.app = app


def test_get_db_yields_a_usable_connection_to_the_configured_path(tmp_path):
    db_path = tmp_path / "hail_mary.db"
    open_database(db_path).close()  # schema must already exist, like main.py's startup call

    gen = get_db(_FakeRequest(_FakeApp(db_path)))
    conn = next(gen)
    conn.execute("SELECT 1")
    gen.close()


def test_get_db_closes_the_connection_when_the_request_ends(tmp_path):
    db_path = tmp_path / "hail_mary.db"
    open_database(db_path).close()

    gen = get_db(_FakeRequest(_FakeApp(db_path)))
    conn = next(gen)
    gen.close()

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_concurrent_requests_never_share_one_connection_object(tmp_path):
    """Direct regression test for the original (2026-09-11) bug shape: two
    concurrent callers of get_db() must never receive the *same* connection
    object -- each request gets its own, so there is nothing left to race on."""
    db_path = tmp_path / "hail_mary.db"
    open_database(db_path).close()

    # Keep every generator+connection alive (in `held`) until after all
    # threads finish and the assertion runs -- id() can be reused once an
    # object is garbage-collected, so closing/dropping connections mid-test
    # would risk a false "duplicate id" from unrelated objects, not a real
    # collision.
    held: list[tuple] = []
    collect_lock = threading.Lock()

    def use_dependency():
        gen = get_db(_FakeRequest(_FakeApp(db_path)))
        conn = next(gen)
        with collect_lock:
            held.append((gen, conn))

    threads = [threading.Thread(target=use_dependency) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    seen_ids = [id(conn) for _gen, conn in held]
    assert len(set(seen_ids)) == len(seen_ids), "two callers shared the same connection object"

    for gen, _conn in held:
        gen.close()


@pytest.fixture
def client_and_db(tmp_path):
    db_path = tmp_path / "hail_mary_test.db"
    app = create_app(db_path)
    return TestClient(app), db_path


def test_high_concurrency_load_does_not_lose_rows_or_deadlock(client_and_db):
    """End-to-end regression test for both bugs at once, through real ASGI
    dispatch (the 2026-09-11 fix's own verification was a manual, uncommitted
    script driving TestClient -- it never became a real test, and the
    lock-only unit test drove get_db() directly rather than through FastAPI's
    actual dependency/threadpool machinery, so neither could have caught the
    2026-09-13 deadlock bug). n is chosen comfortably above anyio's default
    40-thread pool on purpose: that's exactly the regime where the
    lock-across-threadpool-dispatch bug wedges the whole app. Bounded with a
    timeout so a real deadlock fails this test instead of hanging forever."""
    client, db_path = client_and_db
    n = 80

    def post_one(i):
        # window_start/window_end are unique per i, so every row is a
        # distinct insert regardless of the 3-way zone_id reuse -- this
        # isolates "did every row actually land" from occupancy/live's
        # separate latest-per-zone semantics (not a row-count endpoint).
        payload = [{"zone_id": f"zone{i % 3}", "window_start": f"t{i}-s", "window_end": f"t{i}-e", "count": i}]
        return client.post("/api/v1/occupancy", json=payload)

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(post_one, i) for i in range(n)]
        results = [f.result(timeout=30) for f in as_completed(futures, timeout=30)]

    assert all(r.status_code == 200 for r in results)
    verify_conn = sqlite3.connect(str(db_path))
    row_count = verify_conn.execute("SELECT COUNT(*) FROM occupancy").fetchone()[0]
    verify_conn.close()
    assert row_count == n, f"expected {n} rows, found {row_count} -- rows were lost under concurrent load"
