-- PoleWatch 백엔드 스키마
-- 1) device_sessions : 기기 상태(주행 세션 지표·시계열)  ─ 화면 C
-- 2) poles           : 온디바이스 판정 결과(전주 위험등급·사진)  ─ 실시간 전송

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

-- 온디바이스 판정 결과 (전주 단위). Jetson이 판정 후 실시간으로 전송한다.
CREATE TABLE IF NOT EXISTS poles (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER REFERENCES device_sessions(id),
    pole_no     TEXT,                        -- 전주 번호(있으면)
    grade       TEXT NOT NULL,               -- danger | caution | safe (위험/주의/양호)
    hazard_type TEXT,                         -- nest | tree (까치집/수목)
    conf        REAL,                         -- 판정 신뢰도 0~1
    lat         REAL,                         -- GPS 위도(없으면 NULL)
    lon         REAL,                         -- GPS 경도
    recorded_at TEXT NOT NULL,                -- 판정 시각(ISO8601)
    image_path  TEXT                          -- best-frame 크롭 사진 파일명 (images/ 하위)
);

CREATE INDEX IF NOT EXISTS idx_poles_grade   ON poles(grade);
CREATE INDEX IF NOT EXISTS idx_poles_session ON poles(session_id);
