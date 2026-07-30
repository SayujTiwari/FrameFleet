from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any


class MediaProbeError(Exception):
    pass


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool


def probe_video(source_path: Path) -> VideoProbe:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise MediaProbeError("FFprobe could not inspect the video") from error

    if result.returncode != 0:
        raise MediaProbeError("Uploaded file is not readable media")

    try:
        document: dict[str, Any] = json.loads(result.stdout)
        streams = document["streams"]
        format_details = document["format"]
        video_stream = next(
            stream for stream in streams if stream.get("codec_type") == "video"
        )

        duration_seconds = float(
            format_details.get("duration") or video_stream["duration"]
        )
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        video_codec = str(video_stream["codec_name"])
        format_name = str(format_details["format_name"])
    except (AttributeError, KeyError, StopIteration, TypeError, ValueError) as error:
        raise MediaProbeError("Media does not contain a valid video stream") from error

    if duration_seconds <= 0 or width <= 0 or height <= 0:
        raise MediaProbeError("Video metadata contains invalid values")

    return VideoProbe(
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        video_codec=video_codec,
        format_name=format_name,
        has_audio=any(
            stream.get("codec_type") == "audio" for stream in streams
        ),
    )
