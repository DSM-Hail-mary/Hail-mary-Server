-- PoleWatch 기기 상태 백엔드 스키마
-- Jetson 엣지가 주행 세션 상태를 기록하고, 대시보드가 읽는다.

-- 기기(주행 세션) 상태
CREATE TABLE IF NOT EXISTS device_sessions (
    id            INTEGER PRIMARY KEY,
    device        TEXT,                     -- "Jetson Nano"
    date          TEXT NOT NULL,            -- 주행 날짜
    start_time    TEXT,
    end_time      TEXT,
    duration_sec  INTEGER,
    max_temp      REAL,
    avg_temp      REAL,
    throttle_temp REAL,                     -- 스로틀링 기준 온도
    avg_power     REAL,
    max_power     REAL,
    frame_drops   INTEGER,
    total_frames  INTEGER,
    gps_reception REAL,                     -- 0~1
    telemetry     TEXT                      -- JSON: {"t":[],"temp":[],"power":[],"drops":[],"gps":[]}
);
