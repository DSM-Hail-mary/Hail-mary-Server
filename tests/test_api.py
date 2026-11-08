"""프론트 계약(docs/API.md) 회귀 테스트 — /api/v1 records/drives/sync + WS."""

_JPEG_1PX_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////"
    "////////////////////////////////////////////////////wAALCAABAAEBAREA"
    "/8QAFAABAAAAAAAAAAAAAAAAAAAAA//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8A"
    "H//Z"
)

REC_KEYS = {"id", "poleId", "driveId", "position", "headingDeg", "recordedAt",
            "grade", "hazard", "status", "review", "plannedDate", "basis", "thumbnailUrl",
            "crops", "consecutiveFinds", "previousVisit"}


# ---- 기기 상태 --------------------------------------------------------------
def test_device_latest_empty_404(client):
    r = client.get("/api/device/session/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "세션 기록 없음"


# ---- WS 세션 + 판정 → records/drives 반영 -----------------------------------
def test_ws_session_and_detection_flow(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type": "session_start", "device": "Jetson Nano",
                      "date": "2026-09-27", "start_time": "09:11"})
        ack = ws.receive_json()
        assert ack["event"] == "session_start"
        drive_id = ack["drive_id"]

        ws.send_json({"type": "telemetry", "t": "09:12", "temp": 50,
                      "power": 8, "drops": 0, "gps": 1})
        assert ws.receive_json()["event"] == "telemetry"

        # 판정: 엣지 등급 caution → 프론트 warn 매핑
        ws.send_json({"type": "detection", "grade": "caution", "hazard_type": "nest",
                      "conf": 0.8, "lat": 35.05, "lon": 126.69, "pole_no": "3501-12669-N",
                      "recorded_at": "2026-09-27T09:15:22+09:00", "image_b64": _JPEG_1PX_B64})
        dack = ws.receive_json()
        assert dack["event"] == "detection" and dack["image_saved"] is True

        ws.send_json({"type": "session_end", "end_time": "09:32", "max_temp": 74.0})
        assert ws.receive_json()["event"] == "session_end"

    # records 계약
    recs = client.get("/api/v1/records").json()
    assert len(recs) == 1
    rec = recs[0]
    assert set(rec.keys()) == REC_KEYS
    assert rec["grade"] == "warn"                 # caution → warn
    assert rec["poleId"] == "3501-12669-N"
    assert rec["position"] == {"lat": 35.05, "lng": 126.69}
    assert rec["status"] == "new"
    assert rec["thumbnailUrl"].startswith("/images/")
    assert rec["recordedAt"] == "2026-09-27T09:15:22+09:00"

    # drives / dates
    dates = client.get("/api/v1/drives/dates").json()
    assert dates == [{"date": "2026-09-27", "recordCount": 1}]
    drives = client.get("/api/v1/drives").json()
    assert len(drives) == 1 and drives[0]["id"] == drive_id
    assert drives[0]["route"] == [{"lat": 35.05, "lng": 126.69}]

    # 상세 + 404
    rid = rec["id"]
    assert client.get(f"/api/v1/records/{rid}").json()["id"] == rid
    assert client.get("/api/v1/records/nope").status_code == 404


# ---- PATCH 처리상태/검수 ----------------------------------------------------
def _make_record(client, grade="danger"):
    with client.websocket_connect("/ws/device") as ws:
        gmap = {"danger": "danger", "warn": "caution", "ok": "safe"}
        ws.send_json({"type": "detection", "grade": gmap[grade], "hazard_type": "nest",
                      "conf": 0.9, "lat": 35.0, "lon": 126.0, "pole_no": "P1",
                      "recorded_at": "2026-09-27T10:00:00+09:00"})
        return ws.receive_json()["record_id"]


def test_patch_status_and_review(client):
    rid = _make_record(client, "danger")
    r = client.patch(f"/api/v1/records/{rid}", json={"status": "planned"})
    assert r.status_code == 200 and r.json()["status"] == "planned"
    r = client.patch(f"/api/v1/records/{rid}", json={"review": "false_positive"})
    assert r.json()["review"] == "false_positive"


def test_patch_status_on_ok_rejected_422(client):
    rid = _make_record(client, "ok")
    r = client.patch(f"/api/v1/records/{rid}", json={"status": "checked"})
    assert r.status_code == 422


def test_patch_planned_date_set_and_clear(client):
    rid = _make_record(client, "danger")
    r = client.patch(f"/api/v1/records/{rid}", json={"status": "planned", "plannedDate": "2026-11-20"})
    assert r.status_code == 200
    assert r.json()["status"] == "planned" and r.json()["plannedDate"] == "2026-11-20"
    # 상태를 바꿔도 예정일은 유지
    r = client.patch(f"/api/v1/records/{rid}", json={"status": "removed"})
    assert r.json()["plannedDate"] == "2026-11-20"
    r = client.patch(f"/api/v1/records/{rid}", json={"plannedDate": None})
    assert r.json()["plannedDate"] is None


def test_patch_planned_date_invalid_or_ok_rejected_422(client):
    rid = _make_record(client, "danger")
    assert client.patch(f"/api/v1/records/{rid}", json={"plannedDate": "11/20"}).status_code == 422
    ok = _make_record(client, "ok")
    assert client.patch(f"/api/v1/records/{ok}", json={"plannedDate": "2026-11-20"}).status_code == 422


def test_patch_missing_record_404(client):
    assert client.patch("/api/v1/records/none", json={"status": "checked"}).status_code == 404


# ---- 판정 크롭 검출 박스 ----------------------------------------------------
def _detect_with(client, **extra):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type": "detection", "grade": "danger", "hazard_type": "nest",
                      "conf": 0.9, "lat": 35.0, "lon": 126.0,
                      "recorded_at": "2026-09-27T10:00:00+09:00",
                      "image_b64": _JPEG_1PX_B64, **extra})
        rid = ws.receive_json()["record_id"]
    return client.get(f"/api/v1/records/{rid}").json()["crops"][0]["detections"]


def test_detection_boxes_from_edge(client):
    dets = [{"kind": "nest", "box": {"x": 0.07, "y": 0.07, "w": 0.86, "h": 0.86}, "score": 0.9},
            {"kind": "pole", "box": {"x": 0.4, "y": 0.5, "w": 0.2, "h": 0.5}, "score": 0.7}]
    assert _detect_with(client, detections=dets) == dets


def test_detection_boxes_fallback_whole_crop(client):
    whole = [{"kind": "nest", "box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "score": 0.9}]
    assert _detect_with(client) == whole                                  # 구버전 엣지
    assert _detect_with(client, detections=[{"kind": "bird"}]) == whole   # 형식 오류


# ---- sync -------------------------------------------------------------------
def test_sync_status_and_retry(client):
    assert client.get("/api/v1/sync").json()["state"] == "done"
    assert client.post("/api/v1/sync/retry").json()["state"] == "done"


# ---- WS 방어 ----------------------------------------------------------------
def test_ws_invalid_json_and_bad_grade(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text("nope")
        assert ws.receive_json() == {"type": "error", "detail": "invalid json"}
        ws.send_json({"type": "detection", "grade": "critical"})
        assert ws.receive_json()["type"] == "error"
