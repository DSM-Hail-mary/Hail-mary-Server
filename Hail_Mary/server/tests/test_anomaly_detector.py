"""Red-Green-Refactor: M7 Anomaly Detector -- forecast residual (>=2 sigma,
computed from a real trailing window, not the whole series) simultaneous
with low occupancy. Pure logic, deterministic hand-computed numbers, no
mocking."""
import math

from Hail_Mary.server.core.anomaly_detector import compute_rolling_std, detect_anomalies


def test_compute_rolling_std_uses_only_preceding_window():
    residuals = [0, 2, -2, 1, -1, 0, 2, -2, 1, 20]

    rolling = compute_rolling_std(residuals, window=5)

    assert rolling[0] is None  # no history yet
    assert rolling[3] is None  # only 3 preceding points, need 5
    # index 9's std is computed from residuals[4:9] = [-1, 0, 2, -2, 1]
    expected = math.sqrt(sum(x * x for x in [-1, 0, 2, -2, 1]) / 5)
    assert math.isclose(rolling[9], expected, rel_tol=1e-9)


def _rows(last_actual, occupancy_last=0):
    predicted = [10] * 10
    actual = [10, 12, 8, 11, 9, 10, 12, 8, 11, last_actual]
    occupancy = [3] * 9 + [occupancy_last]
    ts = [f"2026-09-09T{h:02d}:00:00Z" for h in range(10)]
    return [
        {"ts": ts[i], "predicted_kwh": predicted[i], "actual_kwh": actual[i], "occupancy": occupancy[i]}
        for i in range(10)
    ]


def test_detect_anomalies_flags_high_severity_residual_spike_during_low_occupancy():
    rows = _rows(last_actual=30.0, occupancy_last=0)  # residual=20, z ~ 14.1

    events = detect_anomalies(rows, zone_id="hall_main", window=5, sigma_threshold=2.0)

    assert len(events) == 1
    event = events[0]
    assert event["zone_id"] == "hall_main"
    assert event["ts"] == "2026-09-09T09:00:00Z"
    assert event["residual_kwh"] == 20.0
    assert event["occupancy_at_ts"] == 0
    assert event["severity"] == "high"
    assert event["resolved"] is False
    assert event["event_id"]  # non-empty uuid


def test_detect_anomalies_ignores_spike_when_occupancy_is_not_low():
    rows = _rows(last_actual=30.0, occupancy_last=5)  # same residual, but occupied

    events = detect_anomalies(rows, zone_id="hall_main", window=5, sigma_threshold=2.0, low_occupancy_threshold=1)

    assert events == []


def test_detect_anomalies_medium_severity_for_moderate_residual():
    # std at index 9 ~= 1.4142; residual 3.5355 -> z ~= 2.5 (between 2 and 3)
    rows = _rows(last_actual=10 + 3.5355, occupancy_last=0)

    events = detect_anomalies(rows, zone_id="hall_main", window=5, sigma_threshold=2.0)

    assert len(events) == 1
    assert events[0]["severity"] == "medium"


def test_detect_anomalies_no_event_below_sigma_threshold():
    rows = _rows(last_actual=10.5, occupancy_last=0)  # residual 0.5, well under 2 sigma

    events = detect_anomalies(rows, zone_id="hall_main", window=5, sigma_threshold=2.0)

    assert events == []
