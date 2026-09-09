"""M8 Savings / Carbon Calculator (문서/개발_기능명세서.md M8, ↔ F-05/F-06).

Takes two already-known, real kWh series for the same period -- actual
historical usage and a "점유율 연동 제어 가정" control-simulation series
produced elsewhere -- and computes kWh saved, the percentage, the CO2
equivalent (한전 전력 배출계수), and a tree-planting equivalent.

The control-simulation methodology itself is an explicitly open design
question (문서/개발_기능명세서.md 5장 "확정 필요" 목록: "점유율 연동 제어 가정
시뮬레이션의 정확한 백테스트 방법론 정의") -- this module deliberately does not
invent one; it only does the M8 conversion math on whatever real series it is
given.
"""
from typing import List

# 한국전력 국가 전력 부문 평균 배출계수(2022년 잠정치), kgCO2/kWh.
KEPCO_EMISSION_FACTOR_KG_PER_KWH = 0.4781

# 산림청 기준, 30년생 소나무 1그루의 연간 CO2 흡수량, kg/year.
TREE_CO2_ABSORPTION_KG_PER_YEAR = 6.6


def compute_savings(
    period_start: str,
    period_end: str,
    actual_kwh_series: List[float],
    simulated_kwh_series: List[float],
    emission_factor: float = KEPCO_EMISSION_FACTOR_KG_PER_KWH,
    tree_absorption_kg_per_year: float = TREE_CO2_ABSORPTION_KG_PER_YEAR,
) -> dict:
    if len(actual_kwh_series) != len(simulated_kwh_series):
        raise ValueError("actual_kwh_series and simulated_kwh_series must be the same length")
    if not actual_kwh_series:
        raise ValueError("need at least one reading in each series")

    actual_total = sum(actual_kwh_series)
    simulated_total = sum(simulated_kwh_series)
    saved_kwh = actual_total - simulated_total
    saved_pct = (saved_kwh / actual_total * 100) if actual_total else 0.0
    co2_kg = saved_kwh * emission_factor
    tree_equivalent = co2_kg / tree_absorption_kg_per_year

    return {
        "period_start": period_start,
        "period_end": period_end,
        "saved_kwh": saved_kwh,
        "saved_pct": saved_pct,
        "co2_kg": co2_kg,
        "tree_equivalent": tree_equivalent,
    }
