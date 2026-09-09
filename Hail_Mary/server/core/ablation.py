"""M6 Ablation Evaluator (문서/개발_기능명세서.md M6): compares with-occupancy
vs without-occupancy forecast accuracy (MAE/RMSE) and reports the
improvement percentage the occupancy covariate contributed.
"""
import math
from typing import List, Optional


def compute_mae(predicted: List[float], actual: List[float]) -> float:
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    errors = [abs(p - a) for p, a in zip(predicted, actual)]
    return sum(errors) / len(errors)


def compute_rmse(predicted: List[float], actual: List[float]) -> float:
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    squared_errors = [(p - a) ** 2 for p, a in zip(predicted, actual)]
    return math.sqrt(sum(squared_errors) / len(squared_errors))


def evaluate_ablation(rows: List[dict]) -> dict:
    """rows: dicts with with_occ_kwh (nullable), without_occ_kwh, actual_kwh.

    Rows whose with_occ_kwh is None (real occupancy was unavailable for that
    forecast -- see core.forecast_engine) are excluded from the with-side
    metrics; if none have it, with_occ_mae/rmse/improvement are honestly
    reported as None rather than being computed from partial/fake data.
    """
    n = len(rows)
    if n == 0:
        return {
            "n": 0, "without_occ_mae": None, "without_occ_rmse": None,
            "with_occ_mae": None, "with_occ_rmse": None,
            "mae_improvement_pct": None, "rmse_improvement_pct": None,
            "with_occ_available_count": 0,
        }

    without_pred = [row["without_occ_kwh"] for row in rows]
    actual = [row["actual_kwh"] for row in rows]
    without_mae = compute_mae(without_pred, actual)
    without_rmse = compute_rmse(without_pred, actual)

    with_rows = [row for row in rows if row.get("with_occ_kwh") is not None]
    with_occ_mae = with_occ_rmse = mae_improvement_pct = rmse_improvement_pct = None
    if with_rows:
        with_pred = [row["with_occ_kwh"] for row in with_rows]
        with_actual = [row["actual_kwh"] for row in with_rows]
        with_occ_mae = compute_mae(with_pred, with_actual)
        with_occ_rmse = compute_rmse(with_pred, with_actual)
        # Compare against the without-occupancy baseline on the SAME rows,
        # so the improvement figure isn't skewed by a different row set.
        without_pred_matched = [row["without_occ_kwh"] for row in with_rows]
        without_mae_matched = compute_mae(without_pred_matched, with_actual)
        without_rmse_matched = compute_rmse(without_pred_matched, with_actual)
        if without_mae_matched != 0:
            mae_improvement_pct = (without_mae_matched - with_occ_mae) / without_mae_matched * 100
        if without_rmse_matched != 0:
            rmse_improvement_pct = (without_rmse_matched - with_occ_rmse) / without_rmse_matched * 100

    return {
        "n": n,
        "without_occ_mae": without_mae,
        "without_occ_rmse": without_rmse,
        "with_occ_mae": with_occ_mae,
        "with_occ_rmse": with_occ_rmse,
        "mae_improvement_pct": mae_improvement_pct,
        "rmse_improvement_pct": rmse_improvement_pct,
        "with_occ_available_count": len(with_rows),
    }
