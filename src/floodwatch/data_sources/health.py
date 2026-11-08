"""
Data Source Health Monitor (health.py)
======================================
Monitors ingest freshness, latency, and staleness across meteorological feeds.
Generates source_health.json consumed by runner.py and Streamlit UI badge.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class StreamHealth:
    stream_name: str
    last_valid_utc: str | None
    lag_hours: float
    expected_cadence_h: float
    stale: bool
    fallback_used: bool


@dataclass(frozen=True)
class SourceHealthReport:
    evaluated_at: str
    overall_status: str  # "healthy" | "degraded" | "critical"
    streams: dict[str, StreamHealth]


def evaluate_stream_health(
    stream_name: str,
    last_timestamp: datetime | None,
    expected_cadence_h: float = 1.0,
    now: datetime | None = None,
    fallback_used: bool = False
) -> StreamHealth:
    """Evaluates staleness of a single meteorological ingest stream."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if last_timestamp is None:
        return StreamHealth(
            stream_name=stream_name,
            last_valid_utc=None,
            lag_hours=999.0,
            expected_cadence_h=expected_cadence_h,
            stale=True,
            fallback_used=fallback_used
        )

    if last_timestamp.tzinfo is None:
        last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)

    lag_hours = max(0.0, (now - last_timestamp).total_seconds() / 3600.0)
    is_stale = lag_hours > (2.0 * expected_cadence_h)

    return StreamHealth(
        stream_name=stream_name,
        last_valid_utc=last_timestamp.isoformat(),
        lag_hours=round(lag_hours, 2),
        expected_cadence_h=expected_cadence_h,
        stale=is_stale,
        fallback_used=fallback_used
    )


def build_health_report(
    streams: dict[str, StreamHealth],
    now: datetime | None = None
) -> SourceHealthReport:
    """Constructs comprehensive health status report."""
    if now is None:
        now = datetime.now(timezone.utc)

    stale_count = sum(1 for s in streams.values() if s.stale)
    if stale_count == 0:
        status = "healthy"
    elif stale_count < len(streams):
        status = "degraded"
    else:
        status = "critical"

    return SourceHealthReport(
        evaluated_at=now.isoformat(),
        overall_status=status,
        streams=streams
    )


def save_source_health(report: SourceHealthReport, output_path: Path | str = "data/processed/source_health.json") -> None:
    """Persists health report to disk."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
