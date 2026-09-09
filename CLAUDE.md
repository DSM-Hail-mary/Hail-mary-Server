# Hail-Mary Server

빛가람 AI·ICT 경진대회 출품작 "Hail-Mary"의 백엔드 서버 — 엣지(Jetson, 별도 리포 `Hail-mary-Camera`)가 보낸 점유율 데이터를 받아 전력 수요예측(Chronos-2)·ablation 검증·이상탐지·알림을 처리한다. 이 리포의 규칙은 `Hail-mary-Camera` 리포의 CLAUDE.md와 동일 기준을 따른다.

## 전체 구조

```
Hail-mary-Server/                    (repo root)
├── CLAUDE.md                        ← 이 파일
└── Hail_Mary/
    └── server/
        ├── main.py                  FastAPI 앱 팩토리(create_app) + 진입점
        ├── api/                     occupancy / forecast / anomaly 라우터
        ├── core/                    feature_store, forecast_engine(Chronos-2), ablation, anomaly_detector, notifier
        ├── db/                      SQLite 스키마·연결
        ├── data/raw/bdg2/           실제 BDG2(Building Data Genome Project 2) 다운로드본, SOURCE.txt에 출처 명시
        └── tests/                   전부 실제 데이터/실제 TestClient 기반(모킹 없음)
```

- 엣지가 보내는 payload 계약: `Hail-mary-Camera` 리포의 `Hail_Mary/edge/uplink.py`의 `build_occupancy_payload()` 참고 — `[{"zone_id", "window_start", "window_end", "count"}]` 배치 POST. 이 계약이 바뀌면 양쪽 리포를 함께 확인할 것
- 로컬 실행: `uvicorn Hail_Mary.server.main:app --reload` (리포 루트에서)

## 개발 규칙 (Hail-mary-Camera CLAUDE.md와 동일)

- **모킹 금지**: 테스트든 데모든 목(mock)/가짜 데이터로 대체하지 말고 실제로 동작하는 코드만 추가한다 (예: 공개 데이터셋은 실제로 다운로드해서 쓰고, 없으면 "블로킹됨"이라고 정직하게 표시)
- **테스트 커버리지 90% 이상 유지**
- **컴포넌트 이름은 명확하게 짓는다** — 역할이 이름만 보고 드러나야 함
- **패키지 버전 고정**: `requirements.txt`에 버전을 반드시 명시(`==`)

## TDD 워크플로우 (Red → Green → Refactor)

- **Red**: 실패하는 테스트를 먼저 작성한다
- **Green**: 그 테스트를 통과시키는 최소한의 코드만 작성한다 (오버엔지니어링 금지)
- **Refactor**: 테스트를 계속 통과시키는 상태에서 가독성 개선·중복 제거·성능 최적화를 수행한다

## AI 협업 원칙

- **증강 코딩 vs 바이브 코딩**: 코드 품질, 테스트, 단순성을 중시하되 AI와 협업한다
- **중간 결과 관찰**: AI가 반복 동작, 요청하지 않은 기능 구현, 테스트 삭제 등의 신호를 보이면 즉시 개입한다
- **설계 주도권 유지**: AI가 너무 앞서가지 않도록 개발자가 설계 방향을 제시한다
- **문서화 제안 의무**: 개발 작업 후 CLAUDE.md에 추가하면 좋을 규칙·컨벤션·주의사항이 보이면 반드시 먼저 제안한다
- **규칙 정리 제안**: 가장 적게 참조되는 규칙이 보이면 가끔 삭제 여부를 먼저 물어본다

## 특별 주의 사항

**금지**
- Mock 데이터나 가짜 구현 사용 금지
- 혼자 개발 주도 금지 — 코드 짜놓고 나중에 보고하는 방식 금지, 매 단계 개발자와 함께 확인하며 진행

**권장**
- 재사용 가능한 코드 작성
- 접근성(accessibility) 고려 (대시보드 붙을 때 적용)
- 성능 최적화 고려

## 커밋 규칙

- 하나의 작업이 독립적으로 완료되어 의미 있는 상태가 되었을 때 커밋한다
- 단순한 중간 수정이나 연속적인 명령 수행마다 커밋하지 않는다
- 커밋 메시지 규격: 디스크립션 없이, **영어로** 구현 내용만 **최대 7글자 이내**로 작성 (예: `add api`, `fix bug`)

## 브랜치 전략

- `main` → 작업 단위별로 `feature/*` 브랜치를 하나 판다
- 그 밑에서 세부 작업 단위로 하위 브랜치를 또 판다
- 하위 브랜치 작업이 끝나면 상위 `feature/*` 브랜치로 머지
- `feature/*` 브랜치가 완성되면 `main`으로 머지

## 문제 해결 우선순위

1. 실제 동작하는 해결책 찾기
2. 기존 코드 패턴 분석 후 일관성 유지
3. 타입 안전성 보장
4. 테스트 가능한 구조로 설계

## 현재 상태 (2026-09-09)

- M4(Feature Store)~M9(Notification) 전부 구현·테스트 완료(73개 테스트, 커버리지 99%)
- Forecast Engine: 실제 Amazon Chronos-2(HuggingFace `amazon/chronos-2`) 사용, TTM 폴백 불필요
- 데이터: 실제 BDG2, Panther 사이트 사무용 건물 3개, 2017년 실측치
- `Hail-mary-Camera` 리포의 `uplink.py`/`pipeline.py`와 실제 연동 테스트 완료(POST /api/v1/occupancy 성공, /live 조회 확인)
- **미구현(의도적, 범위 밖)**: M8(절감량·탄소환산 계산), M10 WebSocket, M11 대시보드 프런트엔드
