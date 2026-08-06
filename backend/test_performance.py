from datetime import UTC, datetime, timedelta
import unittest

from backend.performance import calculate_performance_metrics


class CalculatePerformanceMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started_at = datetime(2026, 1, 1, tzinfo=UTC)

    def test_returns_no_measurements_before_processing_starts(self) -> None:
        metrics = calculate_performance_metrics(
            media_duration_seconds=60,
            started_at=None,
            finished_at=None,
            measured_at=self.started_at,
            completed=False,
        )

        self.assertIsNone(metrics.elapsed_seconds)
        self.assertIsNone(metrics.realtime_multiplier)

    def test_measures_active_elapsed_time_without_reporting_speed(self) -> None:
        metrics = calculate_performance_metrics(
            media_duration_seconds=60,
            started_at=self.started_at,
            finished_at=None,
            measured_at=self.started_at + timedelta(seconds=12),
            completed=False,
        )

        self.assertEqual(metrics.elapsed_seconds, 12)
        self.assertIsNone(metrics.realtime_multiplier)

    def test_calculates_completed_realtime_multiplier(self) -> None:
        metrics = calculate_performance_metrics(
            media_duration_seconds=60,
            started_at=self.started_at,
            finished_at=self.started_at + timedelta(seconds=15),
            measured_at=self.started_at + timedelta(seconds=30),
            completed=True,
        )

        self.assertEqual(metrics.elapsed_seconds, 15)
        self.assertEqual(metrics.realtime_multiplier, 4)


if __name__ == "__main__":
    unittest.main()
