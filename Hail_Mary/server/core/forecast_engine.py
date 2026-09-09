"""M5 Forecast Engine (문서/제안서_백엔드추가.md 4.4.1/4.4.2): zero-shot power
demand forecasting, with occupancy provided as a model covariate when real
occupancy data is available for the requested window.

`ForecastEngine` is the abstraction named in the spec ("Chronos2Backend /
TTMBackend 구현체로 교체 가능"). Only Chronos2Backend is implemented here: the
real Amazon Chronos-2 pretrained model
(https://github.com/amazon-science/chronos-forecasting, weights on
HuggingFace Hub as amazon/chronos-2) installed and downloaded successfully in
this environment, so the IBM Granite TTM fallback described in the task was
not needed. A TTMBackend can be added later by implementing the same
`forecast()` method.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class ForecastEngine(ABC):
    """Abstraction over a pretrained zero-shot time-series forecaster."""

    @abstractmethod
    def forecast(
        self,
        target: List[float],
        prediction_length: int,
        past_covariates: Optional[Dict[str, List[float]]] = None,
        future_covariates: Optional[Dict[str, List[float]]] = None,
    ) -> List[float]:
        """Return `prediction_length` median-quantile point forecasts."""
        raise NotImplementedError


class Chronos2Backend(ForecastEngine):
    """Wraps amazon-science/chronos-forecasting's Chronos-2 pipeline."""

    def __init__(self, model_id: str = "amazon/chronos-2", device_map: str = "cpu"):
        # Imported lazily so importing this module doesn't require torch to
        # be installed unless a Chronos2Backend is actually constructed.
        from chronos import BaseChronosPipeline

        self._pipeline = BaseChronosPipeline.from_pretrained(model_id, device_map=device_map)

    def forecast(
        self,
        target: List[float],
        prediction_length: int,
        past_covariates: Optional[Dict[str, List[float]]] = None,
        future_covariates: Optional[Dict[str, List[float]]] = None,
    ) -> List[float]:
        item: dict = {"target": np.asarray(target, dtype="float32")}
        if past_covariates:
            item["past_covariates"] = {k: np.asarray(v, dtype="float32") for k, v in past_covariates.items()}
        if future_covariates:
            item["future_covariates"] = {k: np.asarray(v, dtype="float32") for k, v in future_covariates.items()}

        _, mean = self._pipeline.predict_quantiles(
            [item], prediction_length=prediction_length, quantile_levels=[0.5]
        )
        # mean[0] has shape (n_variates, prediction_length); target was 1-d
        # (univariate) so n_variates == 1 -- flatten to a plain point forecast.
        return mean[0][0].tolist()


_COVARIATE_COLUMNS = ("hour", "dow", "is_holiday", "temp")


def _covariate_dict(frame: pd.DataFrame, columns) -> Dict[str, List[float]]:
    return {col: frame[col].astype("float32").tolist() for col in columns}


def forecast_with_and_without_occupancy(
    engine: ForecastEngine,
    feature_table: pd.DataFrame,
    building_id: str,
    prediction_length: int,
    context_length: Optional[int] = None,
) -> List[dict]:
    """M5 output: with-occupancy / without-occupancy forecasts for the last
    `prediction_length` rows of `feature_table` (used as a held-out window so
    `actual_kwh` is known -- this is how the Ablation Evaluator gets ground
    truth to score against).

    `feature_table` must be the output of core.feature_store.build_feature_table
    for a single building, sorted by timestamp ascending, with at least
    context_length + prediction_length rows.

    If the `occupancy` column has any missing value across the context or
    forecast window, the with-occupancy forecast is honestly reported as
    unavailable (with_occ_kwh=None, occupancy_available=False) rather than
    silently degrading to the without-occupancy value.
    """
    table = feature_table.sort_values("timestamp").reset_index(drop=True)
    if len(table) < prediction_length + 1:
        raise ValueError("feature_table needs more rows than prediction_length")

    context_end = len(table) - prediction_length
    context_start = 0 if context_length is None else max(0, context_end - context_length)
    context = table.iloc[context_start:context_end]
    horizon = table.iloc[context_end:context_end + prediction_length]

    without_occ = engine.forecast(
        target=context["power_kwh"].tolist(),
        prediction_length=prediction_length,
        past_covariates=_covariate_dict(context, _COVARIATE_COLUMNS),
        future_covariates=_covariate_dict(horizon, _COVARIATE_COLUMNS),
    )

    occupancy_available = not context["occupancy"].isna().any() and not horizon["occupancy"].isna().any()
    with_occ = None
    if occupancy_available:
        with_occ = engine.forecast(
            target=context["power_kwh"].tolist(),
            prediction_length=prediction_length,
            past_covariates=_covariate_dict(context, _COVARIATE_COLUMNS + ("occupancy",)),
            future_covariates=_covariate_dict(horizon, _COVARIATE_COLUMNS + ("occupancy",)),
        )

    rows = []
    for i in range(prediction_length):
        rows.append({
            "building_id": building_id,
            "target_ts": horizon.iloc[i]["timestamp"],
            "without_occ_kwh": without_occ[i],
            "with_occ_kwh": with_occ[i] if with_occ is not None else None,
            "actual_kwh": horizon.iloc[i]["power_kwh"],
            "occupancy_available": occupancy_available,
        })
    return rows
