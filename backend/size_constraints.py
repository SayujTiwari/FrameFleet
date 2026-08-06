from dataclasses import dataclass

BYTES_PER_MEBIBYTE = 1024 * 1024
BITS_PER_BYTE = 8
DEFAULT_AUDIO_BITRATE_BPS = 128_000
MINIMUM_VIDEO_BITRATE_BPS = 120_000
MAXIMUM_VIDEO_BITRATE_BPS = 80_000_000
CONTAINER_PAYLOAD_RATIO = 0.94
ADJUSTMENT_SAFETY_RATIO = 0.97


class SizeConstraintError(ValueError):
    pass


@dataclass(frozen=True)
class SizeBudget:
    target_size_bytes: int
    video_bitrate_bps: int
    audio_bitrate_bps: int


def calculate_size_budget(
    *,
    duration_seconds: float,
    max_file_size_mb: float,
    has_audio: bool,
) -> SizeBudget:
    """Translate a final file-size cap into video and audio bitrate budgets."""
    if duration_seconds <= 0 or max_file_size_mb <= 0:
        raise SizeConstraintError("Duration and target size must be positive")

    target_size_bytes = round(max_file_size_mb * BYTES_PER_MEBIBYTE)
    payload_bits = target_size_bytes * BITS_PER_BYTE * CONTAINER_PAYLOAD_RATIO
    audio_bitrate_bps = DEFAULT_AUDIO_BITRATE_BPS if has_audio else 0
    audio_bits = audio_bitrate_bps * duration_seconds
    video_bitrate_bps = int((payload_bits - audio_bits) / duration_seconds)

    if video_bitrate_bps < MINIMUM_VIDEO_BITRATE_BPS:
        raise SizeConstraintError(
            "The requested file size is too small for this video duration"
        )

    return SizeBudget(
        target_size_bytes=target_size_bytes,
        video_bitrate_bps=min(
            video_bitrate_bps,
            MAXIMUM_VIDEO_BITRATE_BPS,
        ),
        audio_bitrate_bps=audio_bitrate_bps,
    )


# math for adjusting mistake
def calculate_adjusted_video_bitrate(
    *,
    current_video_bitrate_bps: int,
    target_size_bytes: int,
    actual_size_bytes: int,
) -> int:
    """Lower the video bitrate in proportion to a measured size overshoot."""
    if (
        current_video_bitrate_bps <= 0
        or target_size_bytes <= 0
        or actual_size_bytes <= 0
    ):
        raise SizeConstraintError("Bitrate and file sizes must be positive")

    adjusted_bitrate = int(
        current_video_bitrate_bps
        * (target_size_bytes / actual_size_bytes)
        * ADJUSTMENT_SAFETY_RATIO
    )
    return max(MINIMUM_VIDEO_BITRATE_BPS, adjusted_bitrate)
