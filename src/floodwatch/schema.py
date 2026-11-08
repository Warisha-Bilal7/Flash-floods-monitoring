"""
Prediction Contract & Parquet File Validator (schema.py)
=========================================================
Frozen Contract (§3.1, §3.7).
Enforces the 6-column schema and validates model output Parquet files.
"""

from __future__ import annotations

import json

import pandas as pd

# Supported modules
VALID_MODULES = frozenset([
    "A_cloudburst_cnn_lstm",
    "B_snowmelt_lstm",
    "fused"
])

# Valid risk tiers
VALID_TIERS = frozenset(["none", "low", "moderate", "high", "severe"])

# Core 6-column prediction contract
REQUIRED_PREDICTION_COLUMNS = [
    "basin_id",
    "timestamp_utc",
    "module",
    "prob",
    "tier",
    "top_drivers"
]

# Complete model-output file schema (§3.7)
REQUIRED_MODEL_FILE_COLUMNS = [
    "basin_id",
    "timestamp_utc",
    "module",
    "split",
    "prob",
    "baseline_prob",
    "source",
    "top_drivers",
    "model_version"
]


class SchemaError(ValueError):
    """Raised when data violates the FloodWatch prediction schema."""


def validate_predictions(df: pd.DataFrame) -> None:
    """
    Validates that a DataFrame conforms to the 6-column prediction contract.
    Additional columns are permitted (additive only).
    """
    if not isinstance(df, pd.DataFrame):
        raise SchemaError(f"Expected pandas DataFrame, got {type(df)}")

    # Check required columns
    missing = [c for c in REQUIRED_PREDICTION_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"Predictions table is missing required columns: {missing}")

    # Validate module column
    modules = set(df["module"].dropna().unique())
    invalid_mods = modules - VALID_MODULES
    if invalid_mods:
        raise SchemaError(f"Unknown module names in predictions: {invalid_mods}")

    # Validate probabilities
    probs = df["prob"]
    if probs.isna().any():
        raise SchemaError("Found NaN values in 'prob' column.")
    if not ((probs >= 0.0) & (probs <= 1.0)).all():
        raise SchemaError("Probabilities must lie strictly within [0.0, 1.0].")

    # Validate timestamps
    ts = df["timestamp_utc"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        raise SchemaError("'timestamp_utc' must be datetime dtype.")
    if ts.dt.tz is None:
        raise SchemaError("'timestamp_utc' must be timezone-aware (UTC).")

    # Validate tiers if present
    tiers = set(df["tier"].dropna().unique())
    invalid_tiers = tiers - VALID_TIERS
    if invalid_tiers:
        raise SchemaError(f"Invalid risk tiers: {invalid_tiers}")


def validate_model_file(
    path_or_df: str | pd.DataFrame,
    expected_module: str,
    grid_index: pd.DataFrame | None = None
) -> None:
    """
    Validates a model output Parquet file against the §3.7 contract.
    Asserts:
      - All §3.7 columns exist
      - Exactly matches expected_module
      - Sorted ascending by (basin_id, timestamp_utc)
      - Unique keys (no duplicate rows)
      - No test-split rows (unless M7 evaluated)
      - Exactly covers all rows defined in grid_index
    """
    if isinstance(path_or_df, str):
        df = pd.read_parquet(path_or_df)
    else:
        df = path_or_df

    # 1. Required columns
    missing = [c for c in REQUIRED_MODEL_FILE_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"Model output file missing columns: {missing}")

    # 2. Module constant
    if not (df["module"] == expected_module).all():
        unique_mods = df["module"].unique().tolist()
        raise SchemaError(f"Expected module '{expected_module}', found: {unique_mods}")

    # 3. Timestamps: UTC, floored to hour
    ts = df["timestamp_utc"]
    if ts.dt.tz is None:
        raise SchemaError("Timestamps must be UTC timezone-aware.")
    if not (ts.dt.minute == 0).all() or not (ts.dt.second == 0).all():
        raise SchemaError("Timestamps must be strictly floored to the hour.")

    # 4. Probabilities & baseline probabilities
    for col in ["prob", "baseline_prob"]:
        vals = df[col]
        if vals.isna().any():
            raise SchemaError(f"NaN values found in '{col}'.")
        if not ((vals >= 0.0) & (vals <= 1.0)).all():
            raise SchemaError(f"Values in '{col}' must be bounded in [0.0, 1.0].")

    # 5. Key uniqueness and sort order
    key_cols = ["basin_id", "timestamp_utc"]
    if df.duplicated(subset=key_cols).any():
        dups = df[df.duplicated(subset=key_cols, keep=False)]
        raise SchemaError(f"Found {len(dups)} duplicate keys in model output.")

    sorted_df = df.sort_values(key_cols).reset_index(drop=True)
    if not df.reset_index(drop=True).equals(sorted_df):
        raise SchemaError("Model output file must be sorted ascending by (basin_id, timestamp_utc).")

    # 6. Validate top_drivers JSON structure
    for raw_driver in df["top_drivers"].head(100):
        try:
            drivers = json.loads(raw_driver)
            if not isinstance(drivers, list):
                raise SchemaError("top_drivers must be a JSON array.")
            if len(drivers) > 3:
                raise SchemaError("top_drivers cannot exceed 3 items.")
        except json.JSONDecodeError as e:
            raise SchemaError(f"Invalid JSON in top_drivers: {e}")

    # 7. Grid alignment if provided
    if grid_index is not None:
        expected_grid = grid_index[grid_index["split"] != "test"]
        actual_keys = set(zip(df["basin_id"], df["timestamp_utc"]))
        expected_keys = set(zip(expected_grid["basin_id"], expected_grid["timestamp_utc"]))
        if actual_keys != expected_keys:
            diff_missing = expected_keys - actual_keys
            diff_extra = actual_keys - expected_keys
            raise SchemaError(
                f"Grid mismatch: {len(diff_missing)} expected rows missing, "
                f"{len(diff_extra)} unexpected extra rows."
            )
