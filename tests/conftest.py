"""테스트 공용 설정: 임시 DB로 격리, 매 테스트마다 테이블 비움."""
import os
import tempfile

os.environ["POLEWATCH_DB"] = os.path.join(tempfile.gettempdir(), "polewatch_test.db")

import pytest
from fastapi.testclient import TestClient

import main
from db import get_conn, init_db
from main import app


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    conn = get_conn()
    for t in ("crops", "records", "drives", "device_sessions", "sync_state"):
        conn.execute(f"DELETE FROM {t}")
    conn.execute("INSERT OR IGNORE INTO sync_state (id, state) VALUES (1, 'done')")
    conn.commit()
    conn.close()
    main._active["id"] = None
    main._active["drive_id"] = None
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
