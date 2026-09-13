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
import math
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    # Hail-mary-Front is its own repo/origin now (M11 moved out 2026-09-10,
    # see the module note above) -- app.js's fetch("/api/v1/...") calls only
    # reach this API when Front is served same-origin (a reverse proxy, or
    # this app statically mounting Front's build). When Front is instead
    # served on its own (e.g. `python -m http.server` per its own README),
    # the browser's cross-origin request would be blocked without this.
    # Wide open (no credentials are ever sent -- no cookies/auth headers
    # this reads from the browser) matches the rest of this app's demo/LAN
    # security posture (API-key auth is opt-in, see require_api_key()).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(occupancy.router)
    app.include_router(forecast.router)
    app.include_router(anomaly.router)
    app.include_router(savings.router)
    app.include_router(last_seen.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default handler echoes the rejected value back in each
        # error's "input" field. When that value is itself a non-finite
        # float (e.g. a residual_kwh: Infinity request body -- exactly the
        # kind of value a Field(allow_inf_nan=False) constraint exists to
        # reject), json.dumps(..., allow_nan=False) -- which every plain
        # JSONResponse uses -- raises ValueError while trying to build the
        # 422 response itself, turning a should-be-422 into an unhandled 500
        # (code review 2026-09-14). jsonable_encoder() first (matching what
        # FastAPI's own default handler does) to turn non-JSON-native things
        # like a model_validator's raw ValueError into plain strings/dicts,
        # then walk the result stringifying any leftover non-finite floats.
        def sanitize(value: object) -> object:
            if isinstance(value, float) and not math.isfinite(value):
                return str(value)
            if isinstance(value, dict):
                return {k: sanitize(v) for k, v in value.items()}
            if isinstance(value, list):
                return [sanitize(v) for v in value]
            return value

        content = sanitize(jsonable_encoder(exc.errors()))
        return JSONResponse(status_code=422, content={"detail": content})

    return app


app = create_app(
    os.environ.get("HAIL_MARY_DB_PATH"), os.environ.get("HAIL_MARY_API_KEY")
)  # pragma: no cover -- module-level singleton exercised via uvicorn, not pytest; create_app() itself is fully covered
