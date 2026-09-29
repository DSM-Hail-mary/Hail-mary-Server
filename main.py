"""
PoleWatch 백엔드 (FastAPI)

통신 구분:
  - 임베디드(Jetson) ↔ 서버 : WebSocket  /ws/device
      · 기기 상태  : session_start → telemetry × N → session_end
      · 판정 결과  : detection (전주 위험등급 + best-frame 사진, 실시간)
  - 프론트엔드      ↔ 서버 : REST
      · 기기 상태  : GET /api/device/session/latest
      · 판정 결과  : GET /api/poles, GET /api/poles/{id}, GET /api/summary

실행:  uvicorn main:app --reload   (server/ 디렉터리에서)
문서:  http://127.0.0.1:8000/docs
"""
import base64
import binascii
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from db import get_conn, init_db, BASE_DIR

TELE_KEYS = ("t", "temp", "power", "drops", "gps")
GRADE_KO = {"danger": "위험", "caution": "주의", "safe": "양호"}
VALID_GRADES = set(GRADE_KO)

IMAGES_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    init_db()          # 시작 시 스키마 보장
    yield


app = FastAPI(title="PoleWatch API", version="0.3.0", lifespan=lifespan)

_origins = os.environ.get("POLEWATCH_CORS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins, allow_methods=["*"], allow_headers=["*"],
)
# 판정 사진(best-frame 크롭) 정적 서빙
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


# =============================================================================
# 응답 스키마
# =============================================================================
class Telemetry(BaseModel):
    t: list[str] = Field(default_factory=list)
    temp: list[Optional[float]] = Field(default_factory=list)
    power: list[Optional[float]] = Field(default_factory=list)
    drops: list[int] = Field(default_factory=list)
    gps: list[int] = Field(default_factory=list)


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


class Pole(BaseModel):
    id: int
    session_id: Optional[int] = None
    pole_no: Optional[str] = None
    grade: str                      # danger|caution|safe
    grade_ko: str                   # 위험/주의/양호 (서버 제공)
    hazard_type: Optional[str] = None
    conf: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    recorded_at: str
    image_url: Optional[str] = None
    roadview_url: Optional[str] = None


class Summary(BaseModel):
    date: Optional[str] = None
    total: int
    danger: int
    caution: int
    safe: int


# =============================================================================
# 공통 헬퍼
# =============================================================================
def _roadview_url(lat, lon) -> Optional[str]:
    if lat is None or lon is None:
        return None
    return f"https://map.kakao.com/link/roadview/{lat},{lon}"


def _pole_dict(r) -> dict:
    return {
        "id": r["id"],
        "session_id": r["session_id"],
        "pole_no": r["pole_no"],
        "grade": r["grade"],
        "grade_ko": GRADE_KO.get(r["grade"], r["grade"]),
        "hazard_type": r["hazard_type"],
        "conf": r["conf"],
        "lat": r["lat"], "lon": r["lon"],
        "recorded_at": r["recorded_at"],
        "image_url": f"/images/{r['image_path']}" if r["image_path"] else None,
        "roadview_url": _roadview_url(r["lat"], r["lon"]),
    }


# =============================================================================
# [프론트엔드 · REST] 기기 상태
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
    return d


# =============================================================================
# [프론트엔드 · REST] 판정 결과 (전주)
# =============================================================================
@app.get("/api/poles", response_model=list[Pole])
def list_poles(
    grade: Optional[str] = Query(None, description="danger|caution|safe"),
    hazard_type: Optional[str] = Query(None, description="nest|tree"),
    session_id: Optional[int] = None,
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    conn = get_conn()
    clauses, params = [], []
    if grade:
        clauses.append("grade = ?"); params.append(grade)
    if hazard_type:
        clauses.append("hazard_type = ?"); params.append(hazard_type)
    if session_id is not None:
        clauses.append("session_id = ?"); params.append(session_id)
    if date:
        clauses.append("substr(recorded_at,1,10) = ?"); params.append(date)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM poles {where} ORDER BY recorded_at DESC", params).fetchall()
    conn.close()
    return [_pole_dict(r) for r in rows]


@app.get("/api/poles/{pole_id}", response_model=Pole)
def get_pole(pole_id: int):
    conn = get_conn()
    r = conn.execute("SELECT * FROM poles WHERE id=?", (pole_id,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, f"전주 없음: {pole_id}")
    return _pole_dict(r)


@app.get("/api/summary", response_model=Summary)
def summary(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    conn = get_conn()
    where, params = "", []
    if date:
        where = "WHERE substr(recorded_at,1,10) = ?"; params = [date]
    rows = conn.execute(
        f"SELECT grade, COUNT(*) c FROM poles {where} GROUP BY grade", params).fetchall()
    conn.close()
    counts = {row["grade"]: row["c"] for row in rows}
    return {
        "date": date,
        "total": sum(counts.values()),
        "danger": counts.get("danger", 0),
        "caution": counts.get("caution", 0),
        "safe": counts.get("safe", 0),
    }


# =============================================================================
# [임베디드(Jetson) · WebSocket]  기기 상태 telemetry + 판정 결과 detection
# =============================================================================
_active = {"id": None, **{k: [] for k in TELE_KEYS}}
_SUMMARY_COLS = ("end_time", "duration_sec", "max_temp", "avg_temp",
                 "throttle_temp", "avg_power", "max_power",
                 "frame_drops", "total_frames", "gps_reception")


def _save_image(pole_id: int, image_b64: str) -> Optional[str]:
    """base64(JPEG)를 images/pole_{id}.jpg로 저장. 실패 시 None."""
    if not image_b64:
        return None
    if "," in image_b64[:64]:                # data:image/jpeg;base64,... 대응
        image_b64 = image_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    fname = f"pole_{pole_id}.jpg"
    with open(os.path.join(IMAGES_DIR, fname), "wb") as f:
        f.write(raw)
    return fname


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
    """
    Jetson 실시간 채널.
    기기상태: session_start / telemetry / session_end
    판정결과: detection (grade[위험/주의/양호] + best-frame 사진)
    서버는 각 메시지에 ack 응답.
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

            if mtype == "session_start":
                conn = get_conn()
                empty = json.dumps({k: [] for k in TELE_KEYS})
                cur = conn.execute(
                    "INSERT INTO device_sessions (device, date, start_time, telemetry)"
                    " VALUES (?,?,?,?)",
                    (msg.get("device"), msg.get("date"), msg.get("start_time"), empty))
                conn.commit()
                sid = cur.lastrowid
                conn.close()
                _active.update({"id": sid, **{k: [] for k in TELE_KEYS}})
                await ws.send_json({"type": "ack", "event": "session_start", "session_id": sid})

            elif mtype == "telemetry":
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
                await ws.send_json({"type": "ack", "event": "telemetry", "points": len(_active["t"])})

            elif mtype == "session_end":
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
                await ws.send_json({"type": "ack", "event": "session_end", "session_id": sid})

            elif mtype == "detection":
                grade = msg.get("grade")
                if grade not in VALID_GRADES:
                    await ws.send_json({"type": "error",
                                        "detail": f"grade must be one of {sorted(VALID_GRADES)}"})
                    continue
                recorded_at = msg.get("recorded_at") or datetime.now().isoformat(timespec="seconds")
                conn = get_conn()
                cur = conn.execute(
                    "INSERT INTO poles (session_id, pole_no, grade, hazard_type, conf,"
                    " lat, lon, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                    (_active["id"], msg.get("pole_no"), grade, msg.get("hazard_type"),
                     msg.get("conf"), msg.get("lat"), msg.get("lon"), recorded_at))
                conn.commit()
                pole_id = cur.lastrowid
                # 사진 저장 후 경로 갱신
                fname = _save_image(pole_id, msg.get("image_b64"))
                if fname:
                    conn.execute("UPDATE poles SET image_path=? WHERE id=?", (fname, pole_id))
                    conn.commit()
                conn.close()
                await ws.send_json({"type": "ack", "event": "detection",
                                    "pole_id": pole_id, "image_saved": bool(fname)})

            else:
                await ws.send_json({"type": "error", "detail": f"unknown type: {mtype}"})
    except WebSocketDisconnect:
        pass


@app.get("/")
def root():
    return {"service": "PoleWatch API", "docs": "/docs"}
