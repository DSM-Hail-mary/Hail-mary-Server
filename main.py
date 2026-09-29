"""
PoleWatch 백엔드 (FastAPI) — 프론트(Hail-mary-Front) 계약 기준

REST (프론트엔드, docs/API.md):
  GET   /api/v1/drives/dates        DriveDate[]
  GET   /api/v1/drives?date=        Drive[]
  GET   /api/v1/records?date=       PoleRecord[]
  GET   /api/v1/records/{id}        PoleRecord
  PATCH /api/v1/records/{id}        PoleRecord   (본문 {status?, review?})
  GET   /api/device/session/latest  DeviceSession (snake_case, v0.2.0)
  GET   /api/v1/sync                SyncStatus
  POST  /api/v1/sync/retry          SyncStatus
  GET   /images/{file}              판정 사진

WebSocket (임베디드 Jetson):
  WS /ws/device : session_start / telemetry / session_end / detection
"""
import base64
import binascii
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional, Union

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_conn, init_db, BASE_DIR

TELE_KEYS = ("t", "temp", "power", "drops", "gps")
KST = timezone(timedelta(hours=9))
# 엣지 등급(danger/caution/safe) → 프론트 등급(danger/warn/ok)
GRADE_MAP = {"danger": "danger", "caution": "warn", "safe": "ok",
             "warn": "warn", "ok": "ok"}

IMAGES_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    init_db()
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO sync_state (id, state) VALUES (1, 'done')")
    conn.commit()
    conn.close()
    yield


app = FastAPI(title="PoleWatch API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("POLEWATCH_CORS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


# =============================================================================
# 응답 스키마 (프론트 domain/types.ts 와 1:1, camelCase)
# =============================================================================
class LatLng(BaseModel):
    lat: float
    lng: float


class Box(BaseModel):
    x: float
    y: float
    w: float
    h: float


class Detection(BaseModel):
    kind: Literal["nest", "tree", "pole"]
    box: Box
    score: float


class Crop(BaseModel):
    id: str
    url: str
    detections: list[Detection]


class GradeBasis(BaseModel):
    metric: Literal["nest_size", "tree_proximity"]
    level: Literal[0, 1, 2]


class PreviousVisit(BaseModel):
    date: str
    thumbnailUrl: str
    basis: Optional[GradeBasis] = None


class PoleRecord(BaseModel):
    id: str
    poleId: Optional[str] = None
    driveId: str
    position: Optional[LatLng] = None
    headingDeg: Optional[float] = None
    recordedAt: str
    grade: Literal["danger", "warn", "ok"]
    hazard: Optional[Literal["nest", "tree"]] = None
    status: Optional[Literal["new", "checked", "planned", "removed"]] = None
    review: Optional[Literal["correct", "false_positive"]] = None
    basis: Optional[GradeBasis] = None
    thumbnailUrl: str
    crops: list[Crop]
    consecutiveFinds: int
    previousVisit: Optional[PreviousVisit] = None


class Drive(BaseModel):
    id: str
    date: str
    startedAt: str
    endedAt: str
    route: list[LatLng]


class DriveDate(BaseModel):
    date: str
    recordCount: int


class Telemetry(BaseModel):
    t: list[str] = []
    temp: list[Optional[float]] = []
    power: list[Optional[float]] = []
    drops: list[int] = []
    gps: list[int] = []


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
# 헬퍼
# =============================================================================
def _iso(date: str, hhmm: str, day_offset: int = 0) -> str:
    """date(YYYY-MM-DD) + HH:MM → ISO8601(+09:00)."""
    base = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    return (base + timedelta(days=day_offset)).isoformat()


def _ensure_tz(iso_str: str) -> str:
    """타임존 표기가 없으면 +09:00을 붙인다."""
    if iso_str and ("+" not in iso_str[10:] and "Z" not in iso_str[10:]):
        return iso_str + "+09:00"
    return iso_str


def _basis(metric, level) -> Optional[dict]:
    if metric is None or level is None:
        return None
    return {"metric": metric, "level": level}


def _previous_visit(conn, pole_id, recorded_at) -> Optional[dict]:
    if not pole_id:
        return None
    row = conn.execute(
        "SELECT recorded_at, thumbnail_url, basis_metric, basis_level FROM records"
        " WHERE pole_id=? AND recorded_at < ? ORDER BY recorded_at DESC LIMIT 1",
        (pole_id, recorded_at)).fetchone()
    if not row:
        return None
    return {"date": row["recorded_at"][:10], "thumbnailUrl": row["thumbnail_url"],
            "basis": _basis(row["basis_metric"], row["basis_level"])}


def _record_dict(conn, r) -> dict:
    crops = conn.execute(
        "SELECT id, url, detections FROM crops WHERE record_id=? ORDER BY seq",
        (r["id"],)).fetchall()
    position = None
    if r["lat"] is not None and r["lng"] is not None:
        position = {"lat": r["lat"], "lng": r["lng"]}
    return {
        "id": r["id"],
        "poleId": r["pole_id"],
        "driveId": r["drive_id"] or "",
        "position": position,
        "headingDeg": r["heading_deg"],
        "recordedAt": r["recorded_at"],
        "grade": r["grade"],
        "hazard": r["hazard"],
        "status": r["status"],
        "review": r["review"],
        "basis": _basis(r["basis_metric"], r["basis_level"]),
        "thumbnailUrl": r["thumbnail_url"],
        "crops": [{"id": c["id"], "url": c["url"],
                   "detections": json.loads(c["detections"])} for c in crops],
        "consecutiveFinds": r["consecutive_finds"],
        "previousVisit": _previous_visit(conn, r["pole_id"], r["recorded_at"]),
    }


# =============================================================================
# REST — 주행 (drives)
# =============================================================================
@app.get("/api/v1/drives/dates", response_model=list[DriveDate])
def list_drive_dates():
    conn = get_conn()
    rows = conn.execute(
        "SELECT substr(recorded_at,1,10) d, COUNT(*) c FROM records"
        " GROUP BY d ORDER BY d DESC").fetchall()
    conn.close()
    return [{"date": r["d"], "recordCount": r["c"]} for r in rows]


@app.get("/api/v1/drives", response_model=list[Drive])
def list_drives(date: Optional[str] = Query(None)):
    conn = get_conn()
    where, params = "", []
    if date:
        where = "WHERE date = ?"; params = [date]
    drives = conn.execute(f"SELECT * FROM drives {where} ORDER BY started_at", params).fetchall()
    out = []
    for d in drives:
        pts = conn.execute(
            "SELECT lat, lng FROM records WHERE drive_id=? AND lat IS NOT NULL"
            " ORDER BY recorded_at", (d["id"],)).fetchall()
        out.append({
            "id": d["id"], "date": d["date"],
            "startedAt": d["started_at"] or "", "endedAt": d["ended_at"] or "",
            "route": [{"lat": p["lat"], "lng": p["lng"]} for p in pts],
        })
    conn.close()
    return out


# =============================================================================
# REST — 기록 (records)
# =============================================================================
@app.get("/api/v1/records", response_model=list[PoleRecord])
def list_records(date: Optional[str] = Query(None)):
    conn = get_conn()
    where, params = "", []
    if date:
        where = "WHERE substr(recorded_at,1,10) = ?"; params = [date]
    rows = conn.execute(
        f"SELECT * FROM records {where} ORDER BY recorded_at DESC", params).fetchall()
    out = [_record_dict(conn, r) for r in rows]
    conn.close()
    return out


@app.get("/api/v1/records/{record_id}", response_model=PoleRecord)
def get_record(record_id: str):
    conn = get_conn()
    r = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "기록을 찾을 수 없습니다")
    out = _record_dict(conn, r)
    conn.close()
    return out


class RecordPatch(BaseModel):
    status: Optional[Literal["new", "checked", "planned", "removed"]] = None
    review: Optional[Literal["correct", "false_positive"]] = None


@app.patch("/api/v1/records/{record_id}", response_model=PoleRecord)
def update_record(record_id: str, patch: RecordPatch = Body(...)):
    conn = get_conn()
    r = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "기록을 찾을 수 없습니다")
    fields = patch.model_dump(exclude_unset=True)
    # 양호(ok) 기록은 처리 상태 대상이 아님
    if "status" in fields and fields["status"] is not None and r["grade"] == "ok":
        conn.close()
        raise HTTPException(422, "양호 기록에는 처리 상태를 지정할 수 없습니다")
    for k, v in fields.items():
        conn.execute(f"UPDATE records SET {k}=? WHERE id=?", (v, record_id))
    conn.commit()
    # 오탐이면 재학습용 폴더 표시(스텁): 실제 이동은 파이프라인/배치에서
    if fields.get("review") == "false_positive":
        os.makedirs(os.path.join(IMAGES_DIR, "_retrain"), exist_ok=True)
    r = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    out = _record_dict(conn, r)
    conn.close()
    return out


# =============================================================================
# REST — 동기화 (sync)
# =============================================================================
def _sync_dict(row) -> dict:
    if not row or row["state"] == "done":
        return {"state": "done",
                "lastSyncedAt": row["last_synced_at"] if row else None}
    if row["state"] == "syncing":
        return {"state": "syncing", "done": row["done"] or 0,
                "total": row["total"] or 0, "lastSyncedAt": row["last_synced_at"]}
    return {"state": "failed", "reason": row["reason"] or "동기화 실패",
            "lastSyncedAt": row["last_synced_at"]}


@app.get("/api/v1/sync")
def get_sync():
    conn = get_conn()
    row = conn.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
    conn.close()
    return _sync_dict(row)


@app.post("/api/v1/sync/retry")
def retry_sync():
    conn = get_conn()
    conn.execute("UPDATE sync_state SET state='done' WHERE id=1")
    conn.commit()
    row = conn.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
    conn.close()
    return _sync_dict(row)


# =============================================================================
# REST — 기기 상태
# =============================================================================
@app.get("/api/device/session/latest", response_model=DeviceSession)
def latest_session():
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
# WebSocket (임베디드) — 기기 telemetry + 판정 detection
# =============================================================================
_active = {"id": None, "drive_id": None, **{k: [] for k in TELE_KEYS}}
_SUMMARY_COLS = ("end_time", "duration_sec", "max_temp", "avg_temp",
                 "throttle_temp", "avg_power", "max_power",
                 "frame_drops", "total_frames", "gps_reception")


def _save_image(rec_id: str, image_b64: Optional[str]) -> Optional[str]:
    if not image_b64:
        return None
    if "," in image_b64[:64]:
        image_b64 = image_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    safe = rec_id.replace("/", "_").replace(":", "_")
    fname = f"{safe}.jpg"
    with open(os.path.join(IMAGES_DIR, fname), "wb") as f:
        f.write(raw)
    return f"/images/{fname}"


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
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
                date = msg.get("date")
                start = msg.get("start_time")
                conn = get_conn()
                empty = json.dumps({k: [] for k in TELE_KEYS})
                cur = conn.execute(
                    "INSERT INTO device_sessions (device, date, start_time, telemetry)"
                    " VALUES (?,?,?,?)", (msg.get("device"), date, start, empty))
                sid = cur.lastrowid
                drive_id = f"drive-{(date or '').replace('-', '')}-{sid}"
                started_at = _iso(date, start) if (date and start) else None
                conn.execute(
                    "INSERT INTO drives (id, date, started_at, session_id) VALUES (?,?,?,?)",
                    (drive_id, date, started_at, sid))
                conn.commit()
                conn.close()
                _active.update({"id": sid, "drive_id": drive_id, **{k: [] for k in TELE_KEYS}})
                await ws.send_json({"type": "ack", "event": "session_start",
                                    "session_id": sid, "drive_id": drive_id})

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
                await ws.send_json({"type": "ack", "event": "telemetry",
                                    "points": len(_active["t"])})

            elif mtype == "session_end":
                if _active["id"] is None:
                    await ws.send_json({"type": "error", "detail": "활성 세션 없음"})
                    continue
                present = [c for c in _SUMMARY_COLS if c in msg]
                conn = get_conn()
                if present:
                    sets = ", ".join(f"{c}=?" for c in present)
                    conn.execute(f"UPDATE device_sessions SET {sets} WHERE id=?",
                                 [msg[c] for c in present] + [_active["id"]])
                # 주행 종료 시각
                row = conn.execute("SELECT date FROM device_sessions WHERE id=?",
                                   (_active["id"],)).fetchone()
                if row and msg.get("end_time"):
                    conn.execute("UPDATE drives SET ended_at=? WHERE id=?",
                                 (_iso(row["date"], msg["end_time"]), _active["drive_id"]))
                conn.commit()
                conn.close()
                sid = _active["id"]
                _active["id"] = None
                _active["drive_id"] = None
                await ws.send_json({"type": "ack", "event": "session_end", "session_id": sid})

            elif mtype == "detection":
                grade = GRADE_MAP.get(msg.get("grade"))
                if grade is None:
                    await ws.send_json({"type": "error",
                                        "detail": "grade must be danger|caution|safe (or warn|ok)"})
                    continue
                recorded_at = _ensure_tz(msg.get("recorded_at")
                                         or datetime.now(KST).isoformat(timespec="seconds"))
                pole_no = msg.get("pole_no")
                date = recorded_at[:10]
                rec_id = f"{date}_{pole_no}" if pole_no else uuid.uuid4().hex[:12]
                hazard = msg.get("hazard_type")
                status = None if grade == "ok" else "new"
                lat, lng = msg.get("lat"), msg.get("lon")
                conn = get_conn()
                # 이전 연속 발견 횟수
                prev = conn.execute(
                    "SELECT consecutive_finds FROM records WHERE pole_id=? AND recorded_at<?"
                    " ORDER BY recorded_at DESC LIMIT 1", (pole_no, recorded_at)).fetchone()
                cf = (prev["consecutive_finds"] + 1) if (prev and grade != "ok") else 1
                # 사진 저장
                thumb = _save_image(rec_id, msg.get("image_b64")) or ""
                conn.execute(
                    "INSERT OR REPLACE INTO records (id, drive_id, pole_id, lat, lng,"
                    " heading_deg, recorded_at, grade, hazard, status, review,"
                    " basis_metric, basis_level, thumbnail_url, consecutive_finds)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec_id, _active["drive_id"], pole_no, lat, lng,
                     msg.get("heading_deg"), recorded_at, grade, hazard, status, None,
                     None, None, thumb, cf))
                # 크롭 1장(사진) — 검출 박스는 vision이 채우면 확장
                conn.execute("DELETE FROM crops WHERE record_id=?", (rec_id,))
                if thumb:
                    det = []
                    if hazard and msg.get("conf") is not None:
                        det = [{"kind": hazard,
                                "box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                                "score": msg["conf"]}]
                    conn.execute(
                        "INSERT INTO crops (id, record_id, seq, url, detections)"
                        " VALUES (?,?,?,?,?)",
                        (f"{rec_id}-c1", rec_id, 1, thumb, json.dumps(det)))
                conn.commit()
                conn.close()
                await ws.send_json({"type": "ack", "event": "detection",
                                    "record_id": rec_id, "image_saved": bool(thumb)})

            else:
                await ws.send_json({"type": "error", "detail": f"unknown type: {mtype}"})
    except WebSocketDisconnect:
        pass


@app.get("/")
def root():
    return {"service": "PoleWatch API", "docs": "/docs"}
