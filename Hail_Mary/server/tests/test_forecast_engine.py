"""Red-Green-Refactor: M5 Forecast Engine.

Loads the REAL pretrained Amazon Chronos-2 model (amazon/chronos-2 on
HuggingFace Hub, downloaded once and cached locally under
~/.cache/huggingface) and runs it on REAL BDG2 power/weather data. No
mocking of the model or its outputs anywhere in this file.

Kept small (short context / short horizon) so the suite stays fast once the
weights are cached; the first run in a fresh environment needs network
access to huggingface.co to download ~a few hundred MB of weights -- if that
network path is unavailable this whole module is the "blocked" component
described in the task (see final report), not something to fake around.
"""
import math

import pytest

from Hail_Mary.server.core.bdg2_loader import load_electricity_readings, load_weather_temperature
from Hail_Mary.server.core.feature_store import build_feature_table
from Hail_Mary.server.core.forecast_engine import Chronos2Backend, forecast_with_and_without_occupancy
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "bdg2"


@pytest.fixture(scope="module")
def engine():
    return Chronos2Backend(model_id="amazon/chronos-2", device_map="cpu")


@pytest.fixture(scope="module")
def real_feature_table():
    power = load_electricity_readings(DATA_DIR / "electricity_2017.csv", "Panther_office_Karla")[:150]
    weather = load_weather_temperature(DATA_DIR / "weather_panther_2017.csv")
    return build_feature_table(
        power_readings=power,
        occupancy_rows=[],  # real BDG2 2017 has no synchronized real occupancy -- see report
        weather_temperature=weather,
        building_id="Panther_office_Karla",
        zone_id="demo_zone",
    )


def test_chronos2_backend_forecasts_real_power_series(engine):
    readings = load_electricity_readings(DATA_DIR / "electricity_2017.csv", "Panther_office_Karla")
    context = [r["kwh"] for r in readings[:120]]

    forecast = engine.forecast(target=context, prediction_length=6)

    assert len(forecast) == 6
    for value in forecast:
        assert not math.isnan(value)
        assert value > 0  # real office electricity draw, never negative


def test_chronos2_backend_covariates_change_the_forecast(engine):
    readings = load_electricity_readings(DATA_DIR / "electricity_2017.csv", "Panther_office_Karla")
    context = [r["kwh"] for r in readings[:120]]
    hours = [int(r["ts"][11:13]) for r in readings[:120]]
    future_hours = [int(readings[120 + i]["ts"][11:13]) for i in range(6)]

    without_cov = engine.forecast(target=context, prediction_length=6)
    with_cov = engine.forecast(
        target=context,
        prediction_length=6,
        past_covariates={"hour": hours},
        future_covariates={"hour": future_hours},
    )

    assert len(with_cov) == len(without_cov) == 6
    # Real model, real inputs: adding an informative covariate must change
    # at least one of the 6 forecast points (not asserting *which* direction).
    assert any(abs(a - b) > 1e-6 for a, b in zip(with_cov, without_cov))


def test_forecast_with_and_without_occupancy_reports_unavailable_when_no_real_occupancy(engine, real_feature_table):
    result = forecast_with_and_without_occupancy(
        engine, real_feature_table, building_id="Panther_office_Karla",
        prediction_length=6, context_length=120,
    )

    assert len(result) == 6
    for row in result:
        assert row["building_id"] == "Panther_office_Karla"
        assert row["actual_kwh"] > 0  # real held-out BDG2 value
        assert row["without_occ_kwh"] > 0
        # Honest reporting: real BDG2 2017 has no synchronized real occupancy
        # for this building/period, so the with-occupancy variant cannot be
        # computed -- must not be silently faked as equal to without_occ.
        assert row["occupancy_available"] is False
        assert row["with_occ_kwh"] is None


def test_forecast_with_and_without_occupancy_uses_real_covariate_when_present(engine):
    power = load_electricity_readings(DATA_DIR / "electricity_2017.csv", "Panther_office_Karla")[:130]
    weather = load_weather_temperature(DATA_DIR / "weather_panther_2017.csv")
    # Full occupancy coverage for every timestamp in this small window --
    # test fixture data with the real payload schema, exercising the
    # with-occupancy code path (as opposed to test-mocking the model/DB).
    occupancy_rows = [
        {"zone_id": "demo_zone", "window_start": r["ts"], "window_end": r["ts"], "count": (i % 10)}
        for i, r in enumerate(power)
    ]
    table = build_feature_table(
        power_readings=power, occupancy_rows=occupancy_rows, weather_temperature=weather,
        building_id="Panther_office_Karla", zone_id="demo_zone",
    )

    result = forecast_with_and_without_occupancy(
        engine, table, building_id="Panther_office_Karla",
        prediction_length=6, context_length=120,
    )

    for row in result:
        assert row["occupancy_available"] is True
        assert row["with_occ_kwh"] is not None
        assert row["with_occ_kwh"] > 0
