from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# # API response schemas returned to the frontend
class ExportSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution: Literal["original", "1080p", "720p", "480p"]
    output_height: int | None
    quality: Literal["high", "balanced", "compact"]


class EncodingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    status: Literal[
        "ready",
        "processing",
        "assembling",
        "completed",
        "failed",
    ]
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    target_segment_seconds: float
    segment_count: int
    completed_segments: int = 0
    export_settings: ExportSettingsResponse | None = None
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool
