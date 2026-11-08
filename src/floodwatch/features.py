"""
Feature Engineering Engine (features.py)
========================================
Transforms raw meteorological series into hydrological and meteorological indicators.
Zero PyTorch or scikit-learn dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_accumulations(series: pd.Series, windows: list[int] | None = None) -> dict[str, pd.Series]:
    """Computes backward rolling sum of precipitation for given hour windows."""
    if windows is None:
        windows = [1, 3, 24, 72]
    accums = {}
    for w in windows:
        accums[f"rain_{w}h"] = series.rolling(window=w, min_periods=1).sum()
    return accums


def compute_degree_day_melt(temp_celsius: pd.Series, base_temp: float = 0.0, degree_factor: float = 2.5) -> pd.Series:
    """Computes daily snowmelt potential via standard degree-day method (mm/day)."""
    excess_temp = np.maximum(0.0, temp_celsius - base_temp)
    # hourly melt rate: (excess * factor) / 24
    return (excess_temp * degree_factor) / 24.0


def compute_rain_on_snow(
    rain_1h: pd.Series,
    temp_2m: pd.Series,
    snow_depth: pd.Series,
    rain_threshold_mm: float = 2.0,
    temp_threshold_c: float = 1.0,
    snow_threshold_cm: float = 5.0
) -> pd.Series:
    """Computes boolean / magnitude interaction term for rain-on-snow melt dynamics."""
    ros_condition = (
        (rain_1h >= rain_threshold_mm) &
        (temp_2m >= temp_threshold_c) &
        (snow_depth >= snow_threshold_cm)
    )
    # Returns precipitation magnitude when condition is met, else 0
    return np.where(ros_condition, rain_1h, 0.0)


def build_feature_table(
    df: pd.DataFrame,
    terrain_susceptibility: float = 0.5
) -> pd.DataFrame:
    """
    Constructs the canonical feature set for a single basin time series.
    Input df must contain:
      ['timestamp_utc', 'precipitation', 'temperature_2m',
       'freezing_level_height', 'snow_depth', 'soil_moisture_0_to_7cm']
    """
    df = df.sort_values("timestamp_utc").reset_index(drop=True).copy()

    # Rename / aliases
    precip = df["precipitation"]
    temp = df["temperature_2m"]
    df["freezing_level_height"]
    snow = df["snow_depth"]
    df["soil_moisture_0_to_7cm"]

    # Rolling rainfall accumulations
    accums = compute_accumulations(precip, [1, 3, 24, 72])
    for col, s in accums.items():
        df[col] = s

    # 6-hour rainfall forecast (rolling forward sum)
    df["rain_forecast_6h"] = precip.iloc[::-1].rolling(window=6, min_periods=1).sum().iloc[::-1].shift(-6).fillna(0.0)

    # Hydrological interactions
    df["degree_day_melt"] = compute_degree_day_melt(temp)
    df["rain_on_snow"] = compute_rain_on_snow(precip, temp, snow)
    df["terrain_susceptibility"] = float(terrain_susceptibility)

    # 6-hour flood target label (for supervised training)
    # Definition: extreme rain (>20mm in 1h or >40mm in 3h or ROS > 10mm)
    flood_signal = (df["rain_1h"] >= 20.0) | (df["rain_3h"] >= 40.0) | (df["rain_on_snow"] >= 10.0)
    df["label_flood_6h"] = flood_signal.iloc[::-1].rolling(window=6, min_periods=1).max().iloc[::-1].shift(-6).fillna(0).astype(int)

    return df
