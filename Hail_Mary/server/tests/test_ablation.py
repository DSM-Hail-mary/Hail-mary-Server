"""Red-Green-Refactor: M6 Ablation Evaluator -- MAE/RMSE for with/without
occupancy forecasts and the improvement percentage. Pure arithmetic, real
(hand-computed) numbers, no mocking."""
import math

from Hail_Mary.server.core.ablation import compute_mae, compute_rmse, evaluate_ablation


def test_compute_mae_known_values():
    # errors: 1, 3, 2 -> mean = 2.0
    assert compute_mae(predicted=[9.0, 12.0, 8.0], actual=[10.0, 9.0, 10.0]) == 2.0


def test_compute_rmse_known_values():
    # errors: 3, 4 -> squared: 9, 16 -> mean 12.5 -> sqrt ~3.5355
    rmse = compute_rmse(predicted=[7.0, 6.0], actual=[10.0, 10.0])
    assert math.isclose(rmse, math.sqrt(12.5), rel_tol=1e-9)


def test_evaluate_ablation_reports_improvement_when_with_occupancy_is_more_accurate():
    rows = [
        {"with_occ_kwh": 10.0, "without_occ_kwh": 8.0, "actual_kwh": 10.0},
        {"with_occ_kwh": 10.0, "without_occ_kwh": 6.0, "actual_kwh": 10.0},
    ]
    # without errors: 2, 4 -> MAE 3.0 ; with errors: 0, 0 -> MAE 0.0
    result = evaluate_ablation(rows)

    assert result["n"] == 2
    assert result["without_occ_mae"] == 3.0
    assert result["with_occ_mae"] == 0.0
    assert result["mae_improvement_pct"] == 100.0


def test_evaluate_ablation_negative_improvement_when_with_occupancy_is_worse():
    rows = [
        {"with_occ_kwh": 20.0, "without_occ_kwh": 12.0, "actual_kwh": 10.0},
    ]
    result = evaluate_ablation(rows)

    assert result["without_occ_mae"] == 2.0
    assert result["with_occ_mae"] == 10.0
    assert result["mae_improvement_pct"] < 0


def test_evaluate_ablation_excludes_rows_missing_with_occ_and_flags_unavailable():
    rows = [
        {"with_occ_kwh": None, "without_occ_kwh": 8.0, "actual_kwh": 10.0},
        {"with_occ_kwh": None, "without_occ_kwh": 9.0, "actual_kwh": 10.0},
    ]

    result = evaluate_ablation(rows)

    assert result["n"] == 2
    assert result["with_occ_mae"] is None
    assert result["mae_improvement_pct"] is None
    assert result["with_occ_available_count"] == 0


def test_evaluate_ablation_empty_rows_returns_none_metrics():
    result = evaluate_ablation([])
    assert result["n"] == 0
    assert result["without_occ_mae"] is None
    assert result["with_occ_mae"] is None
    assert result["mae_improvement_pct"] is None
