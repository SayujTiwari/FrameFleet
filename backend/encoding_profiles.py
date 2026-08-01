from dataclasses import dataclass


# translating the choices into FFmpeg parameters
@dataclass(frozen=True)
class EncodingProfile:
    crf: int
    preset: str


# different qualities
ENCODING_PROFILES = {
    "high": EncodingProfile(crf=18, preset="medium"),
    "balanced": EncodingProfile(crf=23, preset="veryfast"),
    "compact": EncodingProfile(crf=28, preset="fast"),
}

OUTPUT_HEIGHTS = {
    "original": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}
