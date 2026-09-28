"""
PoleWatch 기기 상태 백엔드 (FastAPI) — 명세서(문서/API_명세서.md) 기준 구현

통신 구분:
  - 임베디드(Jetson) ↔ 서버 : WebSocket  (§2, 주행 중 실시간 telemetry 수신/저장)
  - 프론트엔드      ↔ 서버 : REST       (§1, 기기 상태 조회)

실행:  uvicorn main:app --reload   (server/ 디렉터리에서)
문서:  http://127.0.0.1:8000/docs
"""
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import get_conn, init_db


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    init_db()          # 시작 시 스키마 보장
    yield


app = FastAPI(title="PoleWatch Device API", version="0.2.0", lifespan=lifespan)

# CORS: 기본 전체 허용(개발). 배포 시 POLEWATCH_CORS="https://a,https://b" 로 제한.
_origins = os.environ.get("POLEWATCH_CORS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins, allow_methods=["*"], allow_headers=["*"],
)

TELE_KEYS = ("t", "temp", "power", "drops", "gps")


# =============================================================================
# 응답 스키마 (명세서 §1 필드 레퍼런스와 1:1 대응)
# =============================================================================
class Telemetry(BaseModel):
    t: list[str] = Field(default_factory=list)                 # x축 시각 HH:MM
    temp: list[Optional[float]] = Field(default_factory=list)  # 온도(°C), 센서 실패 시 null
    power: list[Optional[float]] = Field(default_factory=list)  # 전력(W), 센서 실패 시 null
    drops: list[int] = Field(default_factory=list)             # 구간별 프레임 드롭
    gps: list[int] = Field(default_factory=list)               # GPS 수신 1/0


class DeviceSession(BaseModel):
    id: int
    device: Optional[str] = None
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_sec: Optional[int] = None
    max_temp: Optional[float] = None
    avg_temp: Optional[float] = None
    throttle_temp: Optional[float] = None
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    frame_drops: Optional[int] = None
    total_frames: Optional[int] = None
    gps_reception: Optional[float] = None
    telemetry: Telemetry


# =============================================================================
# [프론트엔드 · REST] §1 최신 세션 상태
# =============================================================================
@app.get("/api/device/session/latest", response_model=DeviceSession)
def latest_session():
    """가장 최근 주행 세션의 요약 지표 + 시계열. (화면 C)"""
    conn = get_conn()
    r = conn.execute("SELECT * FROM device_sessions ORDER BY date DESC, id DESC "
                     "LIMIT 1").fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "세션 기록 없음")
    d = dict(r)
    d["telemetry"] = json.loads(d["telemetry"]) if d["telemetry"] else {}
    return d  # response_model이 스펙 필드로 검증·필터링


# =============================================================================
# [임베디드(Jetson) · WebSocket] §2 실시간 telemetry 수신
# =============================================================================
# 단일 활성 세션 누적 버퍼 (개발용: 동시 1대 기준)
_active = {"id": None, **{k: [] for k in TELE_KEYS}}

# session_end에서 받을 수 있는 요약 컬럼 (명세서 §2-3)
_SUMMARY_COLS = ("end_time", "duration_sec", "max_temp", "avg_temp",
                 "throttle_temp", "avg_power", "max_power",
                 "frame_drops", "total_frames", "gps_reception")


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
    """
    Jetson이 접속해 주행 세션 telemetry를 실시간 전송한다. (명세서 §2)
    메시지: session_start → telemetry × N → session_end. 서버는 각 메시지에 ack 응답.
    """
    await ws.accept()
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await ws.send_json({"type": "error", "detail": "invalid json"})
                continue
            mtype = msg.get("type")

            if mtype == "session_start":                       # §2-1
                conn = get_conn()
                empty = json.dumps({k: [] for k in TELE_KEYS})
                cur = conn.execute(
                    "INSERT INTO device_sessions (device, date, start_time, telemetry)"
                    " VALUES (?,?,?,?)",
                    (msg.get("device"), msg.get("date"),
                     msg.get("start_time"), empty),
                )
                conn.commit()
                sid = cur.lastrowid
                conn.close()
                _active.update({"id": sid, **{k: [] for k in TELE_KEYS}})
                await ws.send_json({"type": "ack", "event": "session_start",
                                    "session_id": sid})

            elif mtype == "telemetry":                         # §2-2
                if _active["id"] is None:
                    await ws.send_json({"type": "error", "detail": "session_start 먼저 필요"})
                    continue
                for k in TELE_KEYS:
                    _active[k].append(msg.get(k))
                tel = {k: _active[k] for k in TELE_KEYS}
                conn = get_conn()
                conn.execute("UPDATE device_sessions SET telemetry=? WHERE id=?",
                             (json.dumps(tel), _active["id"]))
                conn.commit()
                conn.close()
                await ws.send_json({"type": "ack", "event": "telemetry",
                                    "points": len(_active["t"])})

            elif mtype == "session_end":                       # §2-3
                if _active["id"] is None:
                    await ws.send_json({"type": "error", "detail": "활성 세션 없음"})
                    continue
                present = [c for c in _SUMMARY_COLS if c in msg]
                if present:
                    sets = ", ".join(f"{c}=?" for c in present)
                    vals = [msg[c] for c in present] + [_active["id"]]
                    conn = get_conn()
                    conn.execute(f"UPDATE device_sessions SET {sets} WHERE id=?", vals)
                    conn.commit()
                    conn.close()
                sid = _active["id"]
                _active["id"] = None
                await ws.send_json({"type": "ack", "event": "session_end",
                                    "session_id": sid})

            else:
                await ws.send_json({"type": "error", "detail": f"unknown type: {mtype}"})
    except WebSocketDisconnect:
        pass


@app.get("/")
def root():
    return {"service": "PoleWatch Device API", "docs": "/docs"}
