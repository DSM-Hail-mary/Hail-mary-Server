"""Hail-Mary backend server (FastAPI). 문서/제안서_백엔드추가.md 4.4 기준.

Local dev: `uvicorn Hail_Mary.server.main:app --reload` from the repo root.
DB path defaults to Hail_Mary/server/data/hail_mary.db, overridable with the
HAIL_MARY_DB_PATH environment variable (used by tests to point at a tmp_path).
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from Hail_Mary.server.api import anomaly, forecast, occupancy, savings
from Hail_Mary.server.db.connection import open_database

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "hail_mary.db"

# M11 dashboard: static HTML/CSS/JS, no build step (문서/개발계획서.md 1.1절 #8 --
# REST 폴링 기반, WebSocket 제외). Lives at Hail_Mary/dashboard/, a sibling of
# this file's parent (Hail_Mary/server/main.py -> Hail_Mary/dashboard/).
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


def create_app(db_path=None) -> FastAPI:
    """App factory so tests can each get an isolated SQLite file instead of
    sharing the on-disk demo DB."""
    app = FastAPI(title="Hail-Mary Backend", version="0.1.0")
    app.state.db = open_database(db_path or DEFAULT_DB_PATH)

    app.include_router(occupancy.router)
    app.include_router(forecast.router)
    app.include_router(anomaly.router)
    app.include_router(savings.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if DASHBOARD_DIR.is_dir():
        app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

    return app


app = create_app(os.environ.get("HAIL_MARY_DB_PATH"))  # pragma: no cover -- module-level singleton exercised via uvicorn, not pytest; create_app() itself is fully covered
