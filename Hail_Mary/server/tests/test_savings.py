"""Red-Green-Refactor: M8 Savings/Carbon Calculator (문서/개발_기능명세서.md M8).

compute_savings() takes two REAL, already-known kWh series (actual vs a
control-simulation series produced elsewhere -- the exact simulation
methodology is an explicitly open design question per 문서/개발_기능명세서.md
5장 "확정 필요" list, so this module does not fabricate one) and computes the
kWh saved, the percentage, the CO2 equivalent, and a tree-planting equivalent.
"""
import pytest

from Hail_Mary.server.core.savings import compute_savings


def test_saved_kwh_is_actual_minus_simulated_total():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[10.0, 10.0], simulated_kwh_series=[8.0, 7.0],
    )

    assert result["saved_kwh"] == 5.0


def test_saved_pct_relative_to_actual_total():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[100.0], simulated_kwh_series=[80.0],
    )

    assert result["saved_pct"] == 20.0


def test_co2_kg_uses_emission_factor():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[10.0], simulated_kwh_series=[0.0], emission_factor=0.5,
    )

    assert result["co2_kg"] == 5.0


def test_tree_equivalent_uses_absorption_constant():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[10.0], simulated_kwh_series=[0.0],
        emission_factor=1.0, tree_absorption_kg_per_year=2.0,
    )

    assert result["tree_equivalent"] == 5.0


def test_negative_savings_when_simulated_uses_more_than_actual():
    # Honest reporting: a bad control simulation can show negative savings --
    # never clamp to zero and hide it.
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[10.0], simulated_kwh_series=[15.0],
    )

    assert result["saved_kwh"] == -5.0
    assert result["saved_pct"] == -50.0


def test_uses_default_kepco_emission_factor_and_tree_constant_when_not_given():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[10.0], simulated_kwh_series=[0.0],
    )

    from Hail_Mary.server.core.savings import KEPCO_EMISSION_FACTOR_KG_PER_KWH, TREE_CO2_ABSORPTION_KG_PER_YEAR
    assert result["co2_kg"] == pytest.approx(10.0 * KEPCO_EMISSION_FACTOR_KG_PER_KWH)
    assert result["tree_equivalent"] == pytest.approx(result["co2_kg"] / TREE_CO2_ABSORPTION_KG_PER_YEAR)


def test_rejects_mismatched_series_lengths():
    with pytest.raises(ValueError):
        compute_savings(
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
            actual_kwh_series=[10.0, 10.0], simulated_kwh_series=[8.0],
        )


def test_rejects_empty_series():
    with pytest.raises(ValueError):
        compute_savings(
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
            actual_kwh_series=[], simulated_kwh_series=[],
        )


def test_zero_actual_total_reports_zero_pct_without_dividing_by_zero():
    result = compute_savings(
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-02T00:00:00Z",
        actual_kwh_series=[0.0, 0.0], simulated_kwh_series=[0.0, 0.0],
    )

    assert result["saved_pct"] == 0.0
