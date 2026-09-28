"""명세서(문서/API_명세서.md) 계약 회귀 테스트 — REST §1 / WS §2."""

SPEC_FIELDS = {
    "id", "device", "date", "start_time", "end_time", "duration_sec",
    "max_temp", "avg_temp", "throttle_temp", "avg_power", "max_power",
    "frame_drops", "total_frames", "gps_reception", "telemetry",
}


# ---- §1 REST ----------------------------------------------------------------
def test_latest_empty_returns_404(client):
    r = client.get("/api/device/session/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "세션 기록 없음"


def test_ws_flow_then_rest_matches_spec(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type": "session_start", "device": "Jetson Nano",
                      "date": "2026-09-28", "start_time": "10:00"})
        assert ws.receive_json() == {"type": "ack", "event": "session_start",
                                     "session_id": 1}
        for i in range(3):
            ws.send_json({"type": "telemetry", "t": f"10:0{i}", "temp": 50 + i,
                          "power": 8.0, "drops": i, "gps": 1})
            assert ws.receive_json() == {"type": "ack", "event": "telemetry",
                                         "points": i + 1}
        ws.send_json({"type": "session_end", "end_time": "10:03",
                      "duration_sec": 180, "max_temp": 52.0, "avg_temp": 51.0,
                      "throttle_temp": 87.0, "avg_power": 8.0, "max_power": 8.2,
                      "frame_drops": 3, "total_frames": 5400, "gps_reception": 1.0})
        assert ws.receive_json() == {"type": "ack", "event": "session_end",
                                     "session_id": 1}

    r = client.get("/api/device/session/latest")
    assert r.status_code == 200
    body = r.json()
    # 스펙 필드 집합과 정확히 일치 (누락·초과 없음)
    assert set(body.keys()) == SPEC_FIELDS
    assert body["date"] == "2026-09-28"
    assert body["max_temp"] == 52.0
    assert set(body["telemetry"].keys()) == {"t", "temp", "power", "drops", "gps"}
    assert body["telemetry"]["t"] == ["10:00", "10:01", "10:02"]
    assert body["telemetry"]["drops"] == [0, 1, 2]


# ---- §2 WS 에러/방어 --------------------------------------------------------
def test_ws_telemetry_before_start_errors(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type": "telemetry", "t": "10:00", "temp": 50,
                      "power": 8, "drops": 0, "gps": 1})
        assert ws.receive_json() == {"type": "error", "detail": "session_start 먼저 필요"}


def test_ws_unknown_type_errors(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type": "bogus"})
        assert ws.receive_json() == {"type": "error", "detail": "unknown type: bogus"}


def test_ws_invalid_json_does_not_crash(client):
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text("this-is-not-json")
        assert ws.receive_json() == {"type": "error", "detail": "invalid json"}
        # 연결이 유지되어 이후 정상 메시지도 처리됨
        ws.send_json({"type": "session_start", "device": "X",
                      "date": "2026-09-28", "start_time": "10:00"})
        assert ws.receive_json()["event"] == "session_start"
