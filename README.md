# Hail-Mary Server — PoleWatch 기기 상태 백엔드

PoleWatch(차량 장착형 배전 전주 상단 위험 자동 기록 시스템)의 **기기 상태 백엔드**.
Jetson 엣지가 주행 중 기기 지표(온도·전력·프레임드롭·GPS)를 전송하면 저장하고,
대시보드가 조회한다.

## 아키텍처 — 통신 채널 2개

```
 [Jetson 엣지] ──WS /ws/device──▶ [이 서버] ──GET /api/...──▶ [대시보드]
   실시간 telemetry 전송            SQLite 저장            기기 상태 조회
```

| 채널 | 담당 | 방식 | 엔드포인트 |
|---|---|---|---|
| 🔌 임베디드(Jetson) → 서버 | 임베디드 | WebSocket | `WS /ws/device` |
| 🖥️ 프론트엔드 → 서버 | 프론트 | REST | `GET /api/device/session/latest` |

## 기술 스택
- **FastAPI** (Python) — REST + WebSocket
- **SQLite** — `device_sessions` 단일 테이블 (별도 DB 서버 불필요)
- **Pydantic** — 응답 스키마 계약 강제
- **pytest** — REST/WS 계약 회귀 테스트

## 실행
```bash
pip install -r requirements.txt
python seed.py                       # (선택) 더미 세션 데이터
uvicorn main:app --reload --port 8000
```
- Swagger 문서: http://127.0.0.1:8000/docs

### 환경변수
| 변수 | 기본값 | 설명 |
|---|---|---|
| `POLEWATCH_DB` | `server/poles.db` | SQLite 파일 경로 |
| `POLEWATCH_CORS` | `*` | 허용 오리진(쉼표 구분) |

## API 요약

### 🖥️ REST — `GET /api/device/session/latest`
최신 주행 세션의 요약 지표 + 시계열을 반환.
```json
{
  "id": 1, "device": "Jetson Nano", "date": "2026-09-27",
  "start_time": "09:11", "end_time": "09:32", "duration_sec": 1260,
  "max_temp": 74.0, "avg_temp": 66.1, "throttle_temp": 87.0,
  "avg_power": 8.4, "max_power": 9.3,
  "frame_drops": 23, "total_frames": 37800, "gps_reception": 0.95,
  "telemetry": { "t": [], "temp": [], "power": [], "drops": [], "gps": [] }
}
```

### 🔌 WebSocket — `WS /ws/device`
Jetson이 주행 세션을 실시간 스트리밍. 서버는 각 메시지에 `ack` 응답.

| 메시지 | 예시 |
|---|---|
| `session_start` | `{"type":"session_start","device":"Jetson Nano","date":"2026-09-27","start_time":"09:11"}` |
| `telemetry` | `{"type":"telemetry","t":"09:12","temp":49.4,"power":8.8,"drops":3,"gps":1}` |
| `session_end` | `{"type":"session_end","end_time":"09:32","max_temp":74.0, ...}` |

흐름: `session_start` → `telemetry` × N → `session_end`.

## 테스트
```bash
pip install -r requirements-dev.txt
python -m pytest -q          # REST/WS 계약 테스트
```

## 구조
```
.
├─ main.py              FastAPI 앱 (REST §1 + WebSocket §2 + 응답 모델)
├─ db.py                SQLite 연결·초기화
├─ schema.sql           device_sessions 스키마
├─ seed.py              더미 세션 시더
├─ tests/               REST/WS 계약 테스트 (pytest)
├─ requirements.txt
└─ requirements-dev.txt
```
