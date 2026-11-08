"""Unit tests for schema.py prediction contract."""

import pandas as pd
import pytest

from floodwatch.schema import SchemaError, validate_predictions


def test_validate_predictions_valid():
    df = pd.DataFrame({
        "basin_id": ["swat_kalam", "swat_madyan"],
        "timestamp_utc": pd.to_datetime(["2022-08-26 04:00", "2022-08-26 05:00"], utc=True),
        "module": ["A_cloudburst_cnn_lstm", "A_cloudburst_cnn_lstm"],
        "prob": [0.75, 0.42],
        "tier": ["high", "moderate"],
        "top_drivers": ['[{"feature": "rain_1h", "weight": 0.8}]', '[]']
    })
    validate_predictions(df)  # Should not raise


def test_validate_predictions_missing_col():
    df = pd.DataFrame({
        "basin_id": ["swat_kalam"],
        "timestamp_utc": pd.to_datetime(["2022-08-26 04:00"], utc=True),
        "prob": [0.75]
    })
    with pytest.raises(SchemaError, match="missing required columns"):
        validate_predictions(df)


def test_validate_predictions_invalid_prob():
    df = pd.DataFrame({
        "basin_id": ["swat_kalam"],
        "timestamp_utc": pd.to_datetime(["2022-08-26 04:00"], utc=True),
        "module": ["A_cloudburst_cnn_lstm"],
        "prob": [1.45],  # Out of bounds
        "tier": ["high"],
        "top_drivers": ["[]"]
    })
    with pytest.raises(SchemaError, match="must lie strictly within"):
        validate_predictions(df)
