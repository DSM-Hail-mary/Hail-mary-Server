# Hail-Mary Server — PoleWatch 기기 상태 백엔드

PoleWatch(차량 장착형 배전 전주 상단 위험 자동 기록 시스템)의 **기기 상태 백엔드**.
Jetson 엣지가 주행 중 기기 지표(온도·전력·프레임드롭·GPS)를 전송하면 저장하고,
대시보드가 조회한다.

## 아키텍처 — 통신 채널 2개

```
 [Jetson 엣지] ──WS /ws/device──▶ [이 서버] ──GET /api/...──▶ [대시보드]
   기기 telemetry + 판정 결과       SQLite 저장            기기 상태 + 판정 조회
   (온디바이스 처리 후 실시간)       (+ 판정 사진)
```

| 채널 | 담당 | 방식 | 엔드포인트 |
|---|---|---|---|
| 🔌 임베디드(Jetson) → 서버 | 임베디드 | WebSocket | `WS /ws/device` (telemetry + detection) |
| 🖥️ 프론트엔드 → 서버 | 프론트 | REST | `GET /api/device/session/latest`, `GET /api/poles` 등 |

**데이터 2종**
- **기기 상태** — 온도·전력·프레임드롭·GPS 시계열 (주행 세션 단위)
- **판정 결과** — 온디바이스 판정된 전주: 등급 `위험/주의/양호` + 위험유형(까치집/수목) + GPS + **best-frame 사진**

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

### 🖥️ REST (프론트엔드)
| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/device/session/latest` | 최신 주행 세션 지표 + 시계열 |
| GET | `/api/poles` | 판정 전주 목록 (`?grade=&hazard_type=&session_id=&date=`) |
| GET | `/api/poles/{id}` | 전주 판정 상세 |
| GET | `/api/summary` | 등급별 집계 (`total/danger/caution/safe`, `?date=`) |
| GET | `/images/{file}` | 판정 사진(best-frame 크롭) |

판정 전주 응답 예:
```json
{ "id": 1, "grade": "danger", "grade_ko": "위험", "hazard_type": "nest",
  "conf": 0.9, "lat": 35.05, "lon": 126.69, "recorded_at": "2026-09-27T09:15:22",
  "image_url": "/images/pole_1.jpg",
  "roadview_url": "https://map.kakao.com/link/roadview/35.05,126.69" }
```

### 🔌 WebSocket — `WS /ws/device` (임베디드)
Jetson이 실시간 스트리밍. 서버는 각 메시지에 `ack` 응답.

| 메시지 | 용도 | 예시 |
|---|---|---|
| `session_start` | 기기 세션 시작 | `{"type":"session_start","device":"Jetson Nano","date":"2026-09-27","start_time":"09:11"}` |
| `telemetry` | 기기 지표 1포인트 | `{"type":"telemetry","t":"09:12","temp":49.4,"power":8.8,"drops":3,"gps":1}` |
| `session_end` | 기기 세션 종료 | `{"type":"session_end","end_time":"09:32","max_temp":74.0, ...}` |
| `detection` | 전주 판정 결과 | `{"type":"detection","grade":"danger","hazard_type":"nest","conf":0.9,"lat":35.05,"lon":126.69,"image_b64":"<JPEG base64>"}` |

- 기기 상태 흐름: `session_start` → `telemetry` × N → `session_end`
- 판정 결과: 주행 중 판정될 때마다 `detection` 전송 (등급 `danger/caution/safe`, best-frame 사진은 `image_b64`)

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
