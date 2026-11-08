"""
Deterministic Local Disk Cache Layer (cache.py)
===============================================
Prevents redundant API calls to Open-Meteo by caching query responses
in parquet or feather format keyed by deterministic SHA-256 hash.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import pandas as pd

DEFAULT_CACHE_DIR = Path("data/processed/cache")


def compute_cache_key(prefix: str, params: dict[str, Any]) -> str:
    """Generate deterministic SHA-256 cache key from query parameters."""
    normalized = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


class DataCache:
    """Manages disk-based serialization and retrieval for meteorological time series."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> pd.DataFrame | None:
        """Retrieve cached DataFrame if available."""
        file_path = self.cache_dir / f"{key}.parquet"
        if file_path.exists():
            try:
                return pd.read_parquet(file_path)
            except Exception:
                return None
        return None

    def put(self, key: str, df: pd.DataFrame) -> None:
        """Store DataFrame to disk cache."""
        file_path = self.cache_dir / f"{key}.parquet"
        temp_path = self.cache_dir / f"{key}.tmp"
        df.to_parquet(temp_path, index=False)
        temp_path.replace(file_path)

    def exists(self, key: str) -> bool:
        """Check if cache file exists."""
        return (self.cache_dir / f"{key}.parquet").exists()

    def clear(self) -> None:
        """Purge all cached files."""
        for f in self.cache_dir.glob("*.parquet"):
            try:
                f.unlink()
            except OSError:
                pass
