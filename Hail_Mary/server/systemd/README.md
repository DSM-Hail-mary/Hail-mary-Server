# hail-mary-server systemd 유닛

왜 필요한가: Camera 리포의 `edge/uplink.py`/`edge/last_seen_uplink.py`가 이 서버에 실시간으로
occupancy·마지막목격 이미지를 올린다. 서버가 재부팅/크래시 후 죽어 있으면 엣지 쪽 재시도 로직
(`buffer.py`)이 로컬에 계속 쌓기만 하고 반영이 안 되므로, edge 파이프라인과 동일하게 서버도
systemd로 자동 복구되게 한다.

## 설치 (실서버)

```bash
sudo cp Hail_Mary/server/systemd/hail-mary-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hail-mary-server
```

`hail-mary-server.service` 안의 `User`, `WorkingDirectory`, `Environment=PYTHONPATH=...`,
`HAIL_MARY_DB_PATH`, `ExecStart`의 python 경로(venv 쓸 경우)는 placeholder이므로 실제 배포
계정·경로에 맞게 먼저 수정한 뒤 설치할 것.

## 로그 확인

```bash
journalctl -u hail-mary-server -f
```

## 헬스체크

```bash
curl http://<서버주소>:8000/health   # {"status":"ok"}
```

## 검증 범위

- `ExecStart`에 명시된 실제 명령(`uvicorn Hail_Mary.server.main:app --host 0.0.0.0 --port 8000`,
  `HAIL_MARY_DB_PATH` 환경변수 포함)은 개발 PC에서 그대로 실행해 `/health`와
  `/api/v1/occupancy/live` 둘 다 200 응답하는 것을 확인함(2026-09-11) — `--host 0.0.0.0` 없이는
  루프백에만 바인딩되어 Jetson 엣지 기기에서 접근 불가능하다는 점도 이때 같이 확인.
- `systemd-analyze verify`는 실행하지 못했음(개발 PC에 systemd 자체가 없는 Windows) — edge 유닛과
  같은 이유로, `[Unit]`/`[Service]`/`[Install]` 섹션 구성은 systemd.unit(5)/systemd.service(5)
  매뉴얼 기준으로 수동 재검토함.
- 재부팅/크래시 복구 동작은 실서버에 유닛을 설치한 뒤에만 확인 가능.
