"""Shared FastAPI dependency for DB access, used by every router in api/.

sqlite3.Connection is not safe to use concurrently from multiple threads
even with check_same_thread=False (that flag only lifts sqlite3's own
same-thread assertion -- it does not add locking). FastAPI dispatches sync
`def` routes/dependencies to a worker-thread pool and `async def` routes
directly on the event loop thread, so two requests arriving close together
really do call execute()/commit() on the one shared connection from
different threads at the same time. Reproduced in code review: concurrent
multi-row inserts silently lost rows and raised
"cannot start a transaction within a transaction" with no lock in place.

get_db() serializes all DB access per app instance by holding
app.state.db_lock for the duration of each request's dependency lifetime.
"""
import sqlite3
from typing import Iterator

from fastapi import Request


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with request.app.state.db_lock:
        yield request.app.state.db
