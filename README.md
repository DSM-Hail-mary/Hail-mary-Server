# Hail-mary-Server

Hail-Mary 백엔드(FastAPI) — Feature Store, Forecast Engine(Chronos-2), Ablation,
Anomaly Detector, Savings/Carbon, Notification, Last-seen 이미지 저장. API 목록은
`Hail-mary-Front` 리포의 `기능명세서.md` 3장 참고.

## 로컬 개발

```bash
pip install -r Hail_Mary/server/requirements.txt
uvicorn Hail_Mary.server.main:app --reload
```

기본 DB 경로는 `Hail_Mary/server/data/hail_mary.db`. `HAIL_MARY_DB_PATH` 환경변수로
바꿀 수 있음(테스트는 각자 격리된 tmp_path DB를 씀).

## 테스트

```bash
pytest Hail_Mary/server --cov=Hail_Mary.server --cov-report=term-missing
```

## 프로덕션 배포

```bash
uvicorn Hail_Mary.server.main:app --host 0.0.0.0 --port 8000
```

- `--reload` 없이, `--host 0.0.0.0`으로 띄워야 Jetson 엣지 기기(`Hail-mary-Camera`의
  `edge/uplink.py`/`last_seen_uplink.py`)의 요청이 도달함. `127.0.0.1`(기본값)은 루프백만 받음.
- `HAIL_MARY_DB_PATH`로 영구 저장 위치를 명시적으로 지정할 것(기본 경로는 리포 안이라
  배포 계정에 따라 쓰기 권한/백업 관점에서 부적절할 수 있음).
- 재부팅/크래시 후 자동 재시작이 필요하면 `Hail_Mary/server/systemd/` 참고
  (`hail-mary-server.service` + 설치 방법).
- 헬스체크: `GET /health` → `{"status":"ok"}`.

## 리포 구조

```
Hail_Mary/server/
├── api/          FastAPI 라우터 (occupancy, forecast, anomaly, savings, last_seen)
├── core/         비즈니스 로직 (feature_store, forecast_engine, ablation, anomaly_detector, notifier, bdg2_loader)
├── db/           SQLite 스키마·커넥션
├── systemd/      프로덕션 배포용 systemd 유닛
├── main.py       FastAPI 앱 팩토리
└── tests/
```
