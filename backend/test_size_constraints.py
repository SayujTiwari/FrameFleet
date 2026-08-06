import unittest

from backend.size_constraints import (
    BYTES_PER_MEBIBYTE,
    DEFAULT_AUDIO_BITRATE_BPS,
    MAXIMUM_VIDEO_BITRATE_BPS,
    MINIMUM_VIDEO_BITRATE_BPS,
    SizeConstraintError,
    calculate_adjusted_video_bitrate,
    calculate_size_budget,
)


class CalculateSizeBudgetTests(unittest.TestCase):
    def test_converts_mebibytes_to_bytes(self) -> None:
        budget = calculate_size_budget(
            duration_seconds=60,
            max_file_size_mb=25,
            has_audio=False,
        )

        self.assertEqual(
            budget.target_size_bytes,
            25 * BYTES_PER_MEBIBYTE,
        )

    def test_reserves_bitrate_for_audio(self) -> None:
        silent_budget = calculate_size_budget(
            duration_seconds=60,
            max_file_size_mb=25,
            has_audio=False,
        )
        audio_budget = calculate_size_budget(
            duration_seconds=60,
            max_file_size_mb=25,
            has_audio=True,
        )

        self.assertEqual(
            silent_budget.video_bitrate_bps - audio_budget.video_bitrate_bps,
            DEFAULT_AUDIO_BITRATE_BPS,
        )

    def test_caps_unnecessarily_large_video_bitrates(self) -> None:
        budget = calculate_size_budget(
            duration_seconds=1,
            max_file_size_mb=50_000,
            has_audio=False,
        )

        self.assertEqual(
            budget.video_bitrate_bps,
            MAXIMUM_VIDEO_BITRATE_BPS,
        )

    def test_rejects_a_target_too_small_for_the_duration(self) -> None:
        with self.assertRaises(SizeConstraintError):
            calculate_size_budget(
                duration_seconds=7_200,
                max_file_size_mb=1,
                has_audio=True,
            )


class CalculateAdjustedVideoBitrateTests(unittest.TestCase):
    def test_reduces_bitrate_in_proportion_to_measured_overshoot(self) -> None:
        adjusted_bitrate = calculate_adjusted_video_bitrate(
            current_video_bitrate_bps=1_000_000,
            target_size_bytes=8_000_000,
            actual_size_bytes=10_000_000,
        )

        self.assertEqual(adjusted_bitrate, 776_000)

    def test_does_not_drop_below_the_minimum_video_bitrate(self) -> None:
        adjusted_bitrate = calculate_adjusted_video_bitrate(
            current_video_bitrate_bps=200_000,
            target_size_bytes=1_000_000,
            actual_size_bytes=10_000_000,
        )

        self.assertEqual(adjusted_bitrate, MINIMUM_VIDEO_BITRATE_BPS)


if __name__ == "__main__":
    unittest.main()
