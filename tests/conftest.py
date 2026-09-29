"""테스트 공용 설정: 임시 DB로 격리, 매 테스트마다 세션 테이블 비움."""
import os
import tempfile

# db/main import 이전에 DB 경로를 임시 파일로 지정 (실 데이터 보호)
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
    conn.execute("DELETE FROM poles")
    conn.execute("DELETE FROM device_sessions")
    conn.commit()
    conn.close()
    # WS 전역 활성 세션 리셋 (테스트 간 누수 방지)
    main._active["id"] = None
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:      # lifespan(init_db) 실행됨
        yield c
