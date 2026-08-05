import unittest

from backend.size_constraints import (
    BYTES_PER_MEBIBYTE,
    DEFAULT_AUDIO_BITRATE_BPS,
    MAXIMUM_VIDEO_BITRATE_BPS,
    SizeConstraintError,
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


if __name__ == "__main__":
    unittest.main()
