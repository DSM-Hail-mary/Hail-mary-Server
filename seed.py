"""더미 데이터 시드 — 프론트 계약(PoleRecord/Drive/SyncStatus) 형태.
화면 A(지도·목록)·B(상세·검수)·C(기기상태)가 http 모드로 뜨도록 채운다.
실행:  python seed.py
"""
import json
import math
import os

from db import get_conn, init_db, BASE_DIR

DATE = "2026-09-27"
DRIVE = "drive-20260927-1"
BASE_LAT, BASE_LNG = 35.05462, 126.69183


def gen_telemetry():
    t, temp, power, drops, gps = [], [], [], [], []
    for i in range(22):
        mm = 11 + i
        t.append(f"09:{mm:02d}")
        temp.append(round(45 + 29 * (1 - math.exp(-i / 6.0)), 1))
        power.append(round(8.4 + 0.9 * math.sin(i / 2.0), 2))
        drops.append(0 if i % 4 else (2 + i % 5))
        gps.append(0 if mm == 31 else 1)
    return {"t": t, "temp": temp, "power": power, "drops": drops, "gps": gps}


def iso(hhmmss):
    return f"{DATE}T{hhmmss}+09:00"


# (pole_no, grade, hazard, status, basis_metric, basis_level, heading, time, located)
RECS = [
    ("3500-12668-E", "ok",     None,   None,  None,            None, 90,  "09:12:04", True),
    ("3501-12669-N", "danger", "nest", "new", "nest_size",     2,    0,   "09:15:22", True),
    ("3502-12669-N", "warn",   "nest", "new", "nest_size",     1,    0,   "09:16:05", True),
    ("3502-12670-E", "ok",     None,   None,  None,            None, 90,  "09:18:31", True),
    ("3502-12671-N", "ok",     None,   None,  None,            None, 0,   "09:19:18", True),
    ("3502-12672-E", "danger", "nest", "new", "nest_size",     2,    90,  "09:20:48", True),
    ("3503-12673-N", "warn",   "tree", "new", "tree_proximity",1,    0,   "09:22:15", True),
    ("3503-12674-E", "ok",     None,   None,  None,            None, 90,  "09:23:40", True),
    ("3504-12675-N", "warn",   "nest", "checked", "nest_size", 1,    0,   "09:25:02", True),
    ("3504-12676-E", "ok",     None,   None,  None,            None, 90,  "09:26:33", True),
    ("3505-12677-E", "danger", "nest", "new", "nest_size",     2,    90,  "09:29:46", False),  # 위치 없음
    ("3505-12678-N", "warn",   "tree", "new", "tree_proximity",1,    0,   "09:30:55", True),
    ("3506-12679-E", "ok",     None,   None,  None,            None, 90,  "09:31:02", False),  # 위치 없음
]


def seed():
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    for t in ("crops", "records", "drives", "device_sessions", "sync_state"):
        cur.execute(f"DELETE FROM {t}")

    # 기기 세션
    cur.execute(
        """INSERT INTO device_sessions
           (id, device, date, start_time, end_time, duration_sec, max_temp, avg_temp,
            throttle_temp, avg_power, max_power, frame_drops, total_frames,
            gps_reception, telemetry)
           VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("Jetson Nano", DATE, "09:11", "09:32", 21 * 60, 74.0, 66.1, 87.0,
         8.4, 9.3, 23, 37800, 0.95, json.dumps(gen_telemetry())))

    # 주행
    cur.execute("INSERT INTO drives (id, date, started_at, ended_at, session_id)"
                " VALUES (?,?,?,?,1)", (DRIVE, DATE, iso("09:11:00"), iso("09:32:00")))

    # 이전 방문(previousVisit 확인용): 3501-12669-N 의 2주 전 기록
    cur.execute(
        """INSERT INTO records (id, drive_id, pole_id, lat, lng, heading_deg,
           recorded_at, grade, hazard, status, basis_metric, basis_level,
           thumbnail_url, consecutive_finds)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("2026-09-13_3501-12669-N", None, "3501-12669-N",
         BASE_LAT, BASE_LNG, 0, "2026-09-13T09:14:00+09:00", "warn", "nest", "checked",
         "nest_size", 1, "/images/sample/3501_prev.jpg", 1))

    # 본 주행 기록들
    for i, (no, grade, hazard, status, bm, bl, heading, hhmmss, located) in enumerate(RECS):
        lat = round(BASE_LAT + i * 0.0009, 5) if located else None
        lng = round(BASE_LNG + i * 0.0011, 5) if located else None
        pole_id = no if located else None      # GPS 미수신이면 ID 미할당
        rec_id = f"{DATE}_{no}" if located else f"nogps-{i:02d}"
        cf = 2 if no == "3501-12669-N" else 1
        cur.execute(
            """INSERT INTO records (id, drive_id, pole_id, lat, lng, heading_deg,
               recorded_at, grade, hazard, status, basis_metric, basis_level,
               thumbnail_url, consecutive_finds)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec_id, DRIVE, pole_id, lat, lng, heading, iso(hhmmss), grade, hazard,
             status, bm, bl, f"/images/sample/{no}_thumb.jpg", cf))
        # 위험/주의 기록엔 크롭 + 검출박스
        if grade != "ok":
            det = [{"kind": hazard, "box": {"x": 0.28, "y": 0.15, "w": 0.22, "h": 0.19},
                    "score": 0.9},
                   {"kind": "pole", "box": {"x": 0.44, "y": 0.01, "w": 0.11, "h": 0.97},
                    "score": 0.97}]
            cur.execute(
                "INSERT INTO crops (id, record_id, seq, url, detections) VALUES (?,?,?,?,?)",
                (f"{rec_id}-c1", rec_id, 1, f"/images/sample/{no}_crop1.jpg", json.dumps(det)))

    # 동기화 상태
    cur.execute("INSERT INTO sync_state (id, state, last_synced_at) VALUES (1,'done',?)",
                (f"{DATE}T18:42:00+09:00",))

    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
    conn.close()
    print(f"시드 완료: 세션 1 · 주행 1 · 기록 {n}건 -> {os.path.join(BASE_DIR, 'poles.db')}")


if __name__ == "__main__":
    seed()
