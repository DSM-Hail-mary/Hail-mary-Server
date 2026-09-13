"""Shared FastAPI dependency for DB access, used by every router in api/.

History (see git log for full detail):
- Originally every router just returned the one shared app.state.db
  connection with no synchronization. sqlite3.Connection is not safe to use
  concurrently from multiple threads even with check_same_thread=False (that
  flag only lifts sqlite3's own same-thread assertion -- it adds no locking),
  and FastAPI dispatches sync routes/dependencies to a worker-thread pool and
  async routes on the event loop thread. Reproduced: concurrent multi-row
  inserts silently lost rows / raised "cannot start a transaction within a
  transaction" (2026-09-11 review).
- First fix wrapped every request's DB use in one process-wide
  threading.Lock. That introduced a WORSE bug: FastAPI/Starlette dispatch
  both dependency resolution and each sync route body (or last_seen.py's
  explicit run_in_threadpool call) through the same shared anyio
  worker-thread pool (default capacity 40). Holding the lock across that
  dispatch boundary meant enough concurrent requests could permanently
  starve the pool -- reproduced against a real running uvicorn process: 80
  concurrent POSTs, only 2 ever completed, the other 78 hung until the
  client's own timeout fired (2026-09-13 review + live repro).

Current fix: no process-wide lock at all. get_db() opens a brand-new
connection scoped to exactly this one request and closes it when the
request ends, so no connection object is ever shared between concurrent
requests (each is only ever touched by whichever single request opened it,
even if that request's dependency-resolution and route-execution steps run
on different pool threads sequentially -- never concurrently). SQLite's own
file-level locking, bounded by connect(timeout=...) as the busy-retry
window, already makes concurrent writers safe without any Python-level
coordination -- and with no cross-request lock, there is nothing left to
deadlock on.
"""
import sqlite3
from typing import Iterator, Optional

from fastapi import Header, HTTPException, Request

# How long a request will wait for SQLite's own internal lock before giving
# up (maps to sqlite3.connect()'s `timeout` -> PRAGMA busy_timeout). Higher
# than the 5s default since this app expects bursts of edge-zone uploads.
BUSY_TIMEOUT_SECONDS = 10.0


def require_api_key(
    request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
) -> None:
    """Write-endpoint guard (제안서_백엔드추가.md 4.4.4: "데모 범위에서는 단순 API
    키로 시작"). Opt-in: if HAIL_MARY_API_KEY isn't set at startup,
    app.state.api_key is None and every request passes unchecked -- this
    keeps local dev and the existing test suite working with no key
    configured, matching how the rest of this app defaults to "open" until a
    deployment explicitly configures otherwise (e.g. HAIL_MARY_DB_PATH).
    Only applied to write routes (POST) -- the dashboard's read-only GETs
    have no secure place to keep a key in a static JS file, so they stay
    open regardless.
    """
    expected = getattr(request.app.state, "api_key", None)
    if expected is None:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    # check_same_thread=False: FastAPI can dispatch a generator dependency's
    # entry (up to `yield`) and exit (after the route returns) to different
    # threadpool threads for the same request -- never concurrently, but not
    # guaranteed to be the same OS thread either. Safe here specifically
    # because this connection is never shared across *requests*, only
    # (sequentially) across steps of this one.
    conn = sqlite3.connect(str(request.app.state.db_path), timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
