"""Regression test for the shared-SQLite-connection thread-safety bug found
in code review (2026-09-11): every router's `get_db()` used to just return
`request.app.state.db` with no synchronization, but FastAPI dispatches sync
routes/dependencies to a worker-thread pool and async routes on the event
loop thread -- so concurrent requests really did call execute()/commit() on
the *same* sqlite3.Connection object from different threads at once,
reproducibly losing rows / raising sqlite3.OperationalError.

Fix: api.deps.get_db is a generator dependency that holds
`request.app.state.db_lock` for the duration of the request, serializing all
DB access. This test exercises the real get_db() generator directly (no
mocking of the thing under test) against a lightweight stand-in for the
Request/app.state shape FastAPI actually passes in."""
import threading
import time

from Hail_Mary.server.api.deps import get_db


class _FakeState:
    def __init__(self):
        self.db_lock = threading.Lock()
        self.db = "connection-sentinel"


class _FakeApp:
    def __init__(self):
        self.state = _FakeState()


class _FakeRequest:
    def __init__(self, app):
        self.app = app


def test_get_db_yields_the_shared_connection():
    app = _FakeApp()
    gen = get_db(_FakeRequest(app))
    assert next(gen) == "connection-sentinel"


def test_get_db_serializes_concurrent_callers():
    app = _FakeApp()
    overlap_detected = threading.Event()
    currently_inside = threading.Event()

    def use_dependency():
        gen = get_db(_FakeRequest(app))
        next(gen)  # enters the `with lock:` block, holds it until closed
        if currently_inside.is_set():
            overlap_detected.set()
        currently_inside.set()
        time.sleep(0.05)  # much larger than thread-start jitter
        currently_inside.clear()
        gen.close()  # releases the lock

    threads = [threading.Thread(target=use_dependency) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not overlap_detected.is_set(), (
        "two callers held the DB dependency at the same time -- "
        "get_db() is not actually serializing access"
    )
