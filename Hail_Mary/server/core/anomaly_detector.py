"""M7 Anomaly Detector (문서/개발_기능명세서.md M7): forecast residual >= 2 sigma
(computed from a trailing rolling window, so no look-ahead) simultaneous with
low occupancy => anomaly event.
"""
import math
from typing import List, Optional
from uuid import uuid4


def compute_rolling_std(residuals: List[float], window: int) -> List[Optional[float]]:
    """Population std of the `window` residuals strictly preceding index i.
    None until at least `window` prior points exist (never uses residuals[i]
    itself, to avoid look-ahead bias)."""
    result: List[Optional[float]] = []
    for i in range(len(residuals)):
        if i < window:
            result.append(None)
            continue
        history = residuals[i - window:i]
        mean = sum(history) / window
        variance = sum((x - mean) ** 2 for x in history) / window
        result.append(math.sqrt(variance))
    return result


def detect_anomalies(
    rows: List[dict],
    zone_id: str,
    window: int = 24,
    sigma_threshold: float = 2.0,
    low_occupancy_threshold: int = 0,
) -> List[dict]:
    """rows: dicts with ts, actual_kwh, predicted_kwh, occupancy, ordered by
    ts ascending. Flags a row as anomalous when |residual| / rolling_std
    exceeds sigma_threshold AND occupancy <= low_occupancy_threshold. A
    residual against a perfectly stable (std==0) baseline is treated as
    anomalous whenever it is nonzero.
    """
    residuals = [row["actual_kwh"] - row["predicted_kwh"] for row in rows]
    rolling_std = compute_rolling_std(residuals, window)

    events = []
    for i, row in enumerate(rows):
        std = rolling_std[i]
        if std is None:
            continue

        if std == 0:
            z = math.inf if residuals[i] != 0 else 0.0
        else:
            z = abs(residuals[i]) / std

        if z < sigma_threshold:
            continue
        if row["occupancy"] > low_occupancy_threshold:
            continue

        severity = "high" if z >= sigma_threshold * 1.5 else "medium"
        events.append({
            "event_id": str(uuid4()),
            "zone_id": zone_id,
            "ts": row["ts"],
            "residual_kwh": residuals[i],
            "occupancy_at_ts": row["occupancy"],
            "severity": severity,
            "resolved": False,
        })
    return events
