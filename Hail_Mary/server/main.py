"""Hail-Mary backend server (FastAPI). 문서/제안서_백엔드추가.md 4.4 기준.

Local dev: `uvicorn Hail_Mary.server.main:app --reload` from the repo root.
DB path defaults to Hail_Mary/server/data/hail_mary.db, overridable with the
HAIL_MARY_DB_PATH environment variable (used by tests to point at a tmp_path).

Write endpoints (POST) are open by default -- set HAIL_MARY_API_KEY to require
a matching `X-API-Key` header on them (제안서_백엔드추가.md 4.4.4's "단순 API
키로 시작"; see api/deps.py require_api_key()). Read-only GET routes (the
dashboard) never require it.

Production: `uvicorn Hail_Mary.server.main:app --host 0.0.0.0 --port 8000`
(no --reload; --host 0.0.0.0 so the Jetson edge device's uplink requests can
reach it -- 127.0.0.1 only accepts loopback). See
Hail_Mary/server/systemd/ for a systemd unit that runs this and restarts
on crash/reboot.
"""
import os
from pathlib import Path

from fastapi import FastAPI

from Hail_Mary.server.api import anomaly, forecast, last_seen, occupancy, savings
from Hail_Mary.server.db.connection import open_database

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "hail_mary.db"

# M11 dashboard moved to the separate Hail-mary-Front repo (2026-09-10) --
# this server only serves the API now, no static mount here.


def create_app(db_path=None, api_key=None) -> FastAPI:
    """App factory so tests can each get an isolated SQLite file instead of
    sharing the on-disk demo DB. api_key=None (the default) leaves write
    endpoints open -- see api/deps.py require_api_key()."""
    resolved_db_path = db_path or DEFAULT_DB_PATH
    app = FastAPI(title="Hail-Mary Backend", version="0.1.0")
    # This connection is kept open only to run schema init once at startup
    # (open_database() also switches the file to WAL mode, a per-file
    # setting that persists for every connection opened against it
    # afterwards) and so tests can seed data directly via app.state.db.
    # Routes never use this connection -- see api/deps.py get_db(), which
    # opens its own short-lived connection per request against db_path.
    app.state.db = open_database(resolved_db_path)
    app.state.db_path = resolved_db_path
    app.state.api_key = api_key

    app.include_router(occupancy.router)
    app.include_router(forecast.router)
    app.include_router(anomaly.router)
    app.include_router(savings.router)
    app.include_router(last_seen.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app(
    os.environ.get("HAIL_MARY_DB_PATH"), os.environ.get("HAIL_MARY_API_KEY")
)  # pragma: no cover -- module-level singleton exercised via uvicorn, not pytest; create_app() itself is fully covered
