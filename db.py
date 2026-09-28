"""SQLite 연결 및 초기화 헬퍼.

DB 경로는 환경변수 POLEWATCH_DB로 override 가능 (테스트/배포용). 기본은 server/poles.db.
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POLEWATCH_DB", os.path.join(BASE_DIR, "poles.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # dict 형태 접근
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """스키마 적용 (테이블 없으면 생성)."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = get_conn()
    conn.executescript(schema)
    conn.commit()
    conn.close()
