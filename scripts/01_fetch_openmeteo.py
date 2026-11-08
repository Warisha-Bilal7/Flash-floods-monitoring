"""
CLI Script: 01_fetch_openmeteo.py
================================
Fetches and caches meteorological series for all 8 northern KP basins.
Usage:
    python scripts/01_fetch_openmeteo.py --start 2021-01-01 --end 2021-03-01
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from floodwatch.data_sources.cache import DataCache
from floodwatch.data_sources.health import (
    build_health_report,
    evaluate_stream_health,
    save_source_health,
)
from floodwatch.data_sources.openmeteo import fetch_openmeteo_series


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Open-Meteo meteorological data.")
    parser.add_argument("--config", default="configs/basins.yaml", help="Basins config path")
    parser.add_argument("--start", default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2021-01-15", help="End date (YYYY-MM-DD)")
    parser.add_argument("--cache-dir", default="data/processed/cache", help="Cache dir")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    basins = cfg.get("basins", {})
    cache = DataCache(args.cache_dir)
    print(f"Fetching meteorological data for {len(basins)} basins ({args.start} to {args.end})...")

    records = []
    latest_ts = None
    for b_id, meta in basins.items():
        print(f"  Ingesting {b_id} (lat={meta['lat']}, lon={meta['lon']})...")
        df = fetch_openmeteo_series(
            lat=meta["lat"],
            lon=meta["lon"],
            start_date=args.start,
            end_date=args.end,
            cache=cache
        )
        df["basin_id"] = b_id
        records.append(df)
        if latest_ts is None or df["timestamp_utc"].max() > latest_ts:
            latest_ts = df["timestamp_utc"].max()

    combined = pd.concat(records, ignore_index=True)
    out_dir = Path("data/processed")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "raw_features.parquet"
    combined.to_parquet(out_file, index=False)
    print(f"Successfully saved {len(combined):,} rows to {out_file}")

    # Generate source health report
    stream_h = evaluate_stream_health("openmeteo_archive", latest_ts.to_pydatetime() if latest_ts else None)
    health_rep = build_health_report({"openmeteo_archive": stream_h})
    save_source_health(health_rep)
    print("Source health report saved to data/processed/source_health.json")


if __name__ == "__main__":
    main()
