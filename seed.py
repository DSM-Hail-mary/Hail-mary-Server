"""더미 데이터 시드 — 스크린샷 C(기기 상태)와 동일한 형태로 채워 API 통합 테스트에 사용.
실행:  python seed.py
"""
import json
import math
import os

from db import get_conn, init_db, BASE_DIR


def gen_telemetry():
    """21분(09:11~09:32) 세션 시계열 — 결정적 합성값."""
    t, temp, power, drops, gps = [], [], [], [], []
    for i in range(22):  # 분 단위 22포인트
        mm = 11 + i
        t.append(f"09:{mm:02d}")
        temp.append(round(45 + 29 * (1 - math.exp(-i / 6.0)), 1))      # 45→74로 상승
        power.append(round(8.4 + 0.9 * math.sin(i / 2.0), 2))          # 8.4 근방
        drops.append(0 if i % 4 else (2 + i % 5))                       # 간헐 드롭
        gps.append(0 if mm == 31 else 1)                               # 09:31 미수신
    return {"t": t, "temp": temp, "power": power, "drops": drops, "gps": gps}


# (grade, hazard_type, conf, lat, lon, time)
POLES = [
    ("danger",  "nest", 0.91, 35.05552, 126.69293, "09:15:22"),
    ("caution", "nest", 0.72, 35.05642, 126.69403, "09:16:05"),
    ("safe",    "tree", 0.65, 35.05731, 126.69512, "09:18:31"),
    ("danger",  "nest", 0.88, 35.05912, 126.69733, "09:20:48"),
    ("caution", "tree", 0.70, 35.06001, 126.69844, "09:22:15"),
    ("safe",    None,   0.55, 35.06182, 126.70066, "09:24:02"),
]


def seed():
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM poles")
    cur.execute("DELETE FROM device_sessions")

    tel = gen_telemetry()
    cur.execute(
        """INSERT INTO device_sessions
           (id, device, date, start_time, end_time, duration_sec,
            max_temp, avg_temp, throttle_temp, avg_power, max_power,
            frame_drops, total_frames, gps_reception, telemetry)
           VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("Jetson Nano", "2026-09-27", "09:11", "09:32", 21 * 60,
         74.0, 66.1, 87.0, 8.4, 9.3, 23, 37800, 0.95, json.dumps(tel)),
    )

    for grade, hazard, conf, lat, lon, hhmmss in POLES:
        cur.execute(
            """INSERT INTO poles
               (session_id, grade, hazard_type, conf, lat, lon, recorded_at)
               VALUES (1,?,?,?,?,?,?)""",
            (grade, hazard, conf, lat, lon, f"2026-09-27T{hhmmss}"),
        )

    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM poles").fetchone()["c"]
    conn.close()
    print(f"시드 완료: 세션 1건, 판정 전주 {n}건 -> {os.path.join(BASE_DIR, 'poles.db')}")


if __name__ == "__main__":
    seed()
