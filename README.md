# Hail-Mary Server — PoleWatch 백엔드

PoleWatch 백엔드. **프론트엔드(Hail-mary-Front) 계약(`docs/API.md`)에 맞춘 REST**와,
Jetson 엣지가 붙는 실시간 **WebSocket**을 제공한다.

## 아키텍처
```
 [Jetson 엣지] ──WS /ws/device──▶ [이 서버] ──REST /api/v1/*──▶ [대시보드(Front)]
   telemetry + 판정(detection)      SQLite + 사진        주행·기록·기기상태·동기화 조회
```

## 기술 스택
- **FastAPI** — REST + WebSocket
- **SQLite** — device_sessions / drives / records / crops / sync_state
- **Pydantic** — 프론트 계약(camelCase, `danger/warn/ok`)과 1:1 응답 모델
- **pytest** — 계약 회귀 테스트

## 실행
```bash
pip install -r requirements.txt
python seed.py                       # 더미 주행·기록·세션
uvicorn main:app --reload --port 8000
```
- Swagger: http://127.0.0.1:8000/docs
- 환경변수: `POLEWATCH_DB`(DB 경로), `POLEWATCH_CORS`(허용 오리진)

## REST API (프론트 계약, `docs/API.md`)
| 메서드 | 경로 | 응답 | 용도 |
|---|---|---|---|
| GET | `/api/v1/drives/dates` | `DriveDate[]` | 기록 있는 날짜 |
| GET | `/api/v1/drives?date=` | `Drive[]` | 주행 경로(route) |
| GET | `/api/v1/records?date=` | `PoleRecord[]` | 전주 기록 (지도·목록) |
| GET | `/api/v1/records/{id}` | `PoleRecord` | 기록 상세 |
| PATCH | `/api/v1/records/{id}` | `PoleRecord` | 처리상태·검수 `{status?, review?}` |
| GET | `/api/device/session/latest` | `DeviceSession` | 기기 상태 (snake_case) |
| GET | `/api/v1/sync` | `SyncStatus` | 동기화 상태 |
| POST | `/api/v1/sync/retry` | `SyncStatus` | 다시 시도 |
| GET | `/images/{file}` | 이미지 | 판정 사진 |

- 등급 `danger`(위험)/`warn`(주의)/`ok`(양호). 시각 ISO8601(+09:00).
- 양호 기록에 `status` PATCH → 422. 없는 기록 → 404 `{"detail": "..."}`.
- 응답 모양 기준: 프론트 `src/domain/types.ts`, 검증: `src/api/schemas.ts`(zod).

## WebSocket — `WS /ws/device` (임베디드)
| 메시지 | 용도 |
|---|---|
| `session_start` | 세션+주행 시작 (drive 생성) |
| `telemetry` | 기기 지표 1포인트 |
| `session_end` | 세션 종료 + 요약 |
| `detection` | 전주 판정 → `records` 저장. 엣지 등급(`danger/caution/safe`)은 서버가 `danger/warn/ok`로 매핑, 사진은 `image_b64` |

## 테스트
```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
프론트 실제 `httpApi`(zod) 검증으로 전 엔드포인트 통과 확인됨.

## 구조
```
main.py · db.py · schema.sql · seed.py · tests/ · requirements*.txt
```
