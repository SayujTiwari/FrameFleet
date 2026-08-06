from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PerformanceMetrics:
    elapsed_seconds: float | None
    realtime_multiplier: float | None


def calculate_performance_metrics(
    *,
    media_duration_seconds: float,
    started_at: datetime | None,
    finished_at: datetime | None,
    measured_at: datetime,
    completed: bool,
) -> PerformanceMetrics:
    if started_at is None:
        return PerformanceMetrics(
            elapsed_seconds=None,
            realtime_multiplier=None,
        )

    end_time = finished_at or measured_at
    elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
    realtime_multiplier = (
        media_duration_seconds / elapsed_seconds
        if completed and elapsed_seconds > 0
        else None
    )

    return PerformanceMetrics(
        elapsed_seconds=elapsed_seconds,
        realtime_multiplier=realtime_multiplier,
    )
