"""
Window Spec & Canonical Grid Index Generator (windows.py)
=========================================================
Frozen Contract (§3.5).
Constructs 72-hour sliding window tensors with 1-hour stride.
Enforces zero data leakage across splits and writes data/processed/grid_index.parquet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LOOKBACK_HOURS = 72
STRIDE_HOURS = 1

CORE_TEMPORAL_FEATURES = [
    "rain_1h",
    "rain_3h",
    "rain_24h",
    "rain_72h",
    "rain_forecast_6h",
    "temperature_2m",
    "freezing_level_height",
    "snow_depth",
    "degree_day_melt",
    "rain_on_snow",
    "soil_moisture_0_to_7cm",
    "terrain_susceptibility"
]


@dataclass(frozen=True)
class ScalerParameters:
    means: dict[str, float]
    stds: dict[str, float]

    def transform(self, df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        res = df.copy()
        for col in columns:
            m = self.means.get(col, 0.0)
            s = self.stds.get(col, 1.0)
            if s <= 1e-6:
                s = 1.0
            res[col] = (res[col] - m) / s
        return res


def fit_train_scaler(train_df: pd.DataFrame, columns: list[str]) -> ScalerParameters:
    """Fits normalization means and stds strictly on train split rows."""
    means = {}
    stds = {}
    for col in columns:
        vals = train_df[col].dropna()
        means[col] = float(vals.mean()) if len(vals) > 0 else 0.0
        s = float(vals.std()) if len(vals) > 1 else 1.0
        stds[col] = s if s > 1e-6 else 1.0
    return ScalerParameters(means=means, stds=stds)


def create_basin_windows(
    basin_df: pd.DataFrame,
    features: list[str] = CORE_TEMPORAL_FEATURES,
    lookback: int = LOOKBACK_HOURS
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """
    Constructs 72h sliding windows for a single basin.
    Returns:
      - X_temporal: (N, 72, C)
      - X_spatial: (N, 3, 3, 3) (rain, temp, freezing over 3x3 patch)
      - Y: (N,) target labels
      - meta_df: DataFrame with (basin_id, timestamp_utc, split)
    """
    df = basin_df.sort_values("timestamp_utc").reset_index(drop=True)
    n = len(df)
    if n <= lookback:
        return (
            np.zeros((0, lookback, len(features)), dtype=np.float32),
            np.zeros((0, 3, 3, 3), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            pd.DataFrame(columns=["basin_id", "timestamp_utc", "split"])
        )

    vals = df[features].values.astype(np.float32)
    labels = df["label_flood_6h"].values.astype(np.float32)
    times = df["timestamp_utc"].values
    splits = df["split"].values
    basin_id = df["basin_id"].iloc[0]

    temp_list = []
    spat_list = []
    y_list = []
    meta_list = []

    # Map spatial channels: rain_1h (0), temperature_2m (5), freezing_level_height (6)
    spatial_indices = [0, 5, 6]

    for i in range(lookback, n):
        # Assert split boundary invariance: Window cannot span different splits!
        window_splits = set(splits[i - lookback : i + 1])
        if len(window_splits) > 1:
            continue  # Discard window crossing chronological split boundary

        t_seq = vals[i - lookback : i]  # (72, C)
        # Synthesize 3x3 patch centered on current cell
        current_spatial = t_seq[-1, spatial_indices]  # (3,)
        patch = np.tile(current_spatial, (3, 3, 1)).transpose(2, 0, 1)  # (3, 3, 3)

        temp_list.append(t_seq)
        spat_list.append(patch)
        y_list.append(labels[i])
        meta_list.append((basin_id, times[i], splits[i]))

    if not temp_list:
        return (
            np.zeros((0, lookback, len(features)), dtype=np.float32),
            np.zeros((0, 3, 3, 3), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            pd.DataFrame(columns=["basin_id", "timestamp_utc", "split"])
        )

    return (
        np.array(temp_list, dtype=np.float32),
        np.array(spat_list, dtype=np.float32),
        np.array(y_list, dtype=np.float32),
        pd.DataFrame(meta_list, columns=["basin_id", "timestamp_utc", "split"])
    )


def export_canonical_grid(
    meta_df: pd.DataFrame,
    output_path: Path | str = "data/processed/grid_index.parquet"
) -> pd.DataFrame:
    """Exports unique canonical grid that both Model A and Model B must evaluate."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    grid = meta_df[["basin_id", "timestamp_utc", "split"]].drop_duplicates().sort_values(
        ["basin_id", "timestamp_utc"]
    ).reset_index(drop=True)
    grid.to_parquet(p, index=False)
    return grid
