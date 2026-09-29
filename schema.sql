-- PoleWatch 백엔드 스키마 (프론트 계약 기준: docs/API.md, domain/types.ts)
--   device_sessions : 기기 상태 (GET /api/device/session/latest)
--   drives          : 주행 1회 (GET /api/v1/drives)
--   records         : 전주 판정 기록 (GET /api/v1/records) — 프론트 PoleRecord
--   crops           : 판정 크롭 + 검출 박스
--   sync_state      : 동기화 상태 (GET /api/v1/sync)

CREATE TABLE IF NOT EXISTS device_sessions (
    id            INTEGER PRIMARY KEY,
    device        TEXT,
    date          TEXT NOT NULL,
    start_time    TEXT,
    end_time      TEXT,
    duration_sec  INTEGER,
    max_temp      REAL,
    avg_temp      REAL,
    throttle_temp REAL,
    avg_power     REAL,
    max_power     REAL,
    frame_drops   INTEGER,
    total_frames  INTEGER,
    gps_reception REAL,
    telemetry     TEXT
);

CREATE TABLE IF NOT EXISTS drives (
    id          TEXT PRIMARY KEY,          -- "drive-20260927-1"
    date        TEXT NOT NULL,             -- YYYY-MM-DD
    started_at  TEXT,                      -- ISO8601 (+09:00)
    ended_at    TEXT,                      -- ISO8601
    session_id  INTEGER REFERENCES device_sessions(id)
);

CREATE TABLE IF NOT EXISTS records (
    id                TEXT PRIMARY KEY,    -- "2026-09-27_3501-12669-N" (전주+날짜) 또는 uuid
    drive_id          TEXT REFERENCES drives(id),
    pole_id           TEXT,                -- GPS 미수신이면 NULL
    lat               REAL,                -- 미수신이면 NULL
    lng               REAL,
    heading_deg       REAL,
    recorded_at       TEXT NOT NULL,       -- ISO8601 (+09:00)
    grade             TEXT NOT NULL,       -- danger | warn | ok
    hazard            TEXT,                -- nest | tree | NULL
    status            TEXT,                -- new|checked|planned|removed | NULL(양호)
    review            TEXT,                -- correct|false_positive | NULL
    basis_metric      TEXT,                -- nest_size|tree_proximity | NULL
    basis_level       INTEGER,             -- 0|1|2 | NULL
    thumbnail_url     TEXT NOT NULL DEFAULT '',
    consecutive_finds INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS crops (
    id         TEXT PRIMARY KEY,           -- "c1"
    record_id  TEXT NOT NULL REFERENCES records(id),
    seq        INTEGER NOT NULL DEFAULT 1,
    url        TEXT NOT NULL,
    detections TEXT NOT NULL DEFAULT '[]'  -- JSON: [{kind,box:{x,y,w,h},score}]
);

CREATE TABLE IF NOT EXISTS sync_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    state          TEXT NOT NULL DEFAULT 'done',   -- done|syncing|failed
    done           INTEGER,
    total          INTEGER,
    reason         TEXT,
    last_synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_date  ON records(substr(recorded_at,1,10));
CREATE INDEX IF NOT EXISTS idx_records_drive ON records(drive_id);
CREATE INDEX IF NOT EXISTS idx_records_pole  ON records(pole_id);
CREATE INDEX IF NOT EXISTS idx_crops_record  ON crops(record_id);
