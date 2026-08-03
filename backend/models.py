from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# API response schemas returned to the frontend
class ExportSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution: Literal["original", "1080p", "720p", "480p"]
    output_height: int | None
    quality: Literal["high", "balanced", "compact"]


class EncodingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    created_at: datetime
    status: Literal[
        "ready",
        "processing",
        "assembling",
        "completed",
        "failed",
        "cancelled",
    ]
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    target_segment_seconds: float
    segment_count: int
    completed_segments: int = 0
    retry_count: int = 0
    export_settings: ExportSettingsResponse | None = None
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool


class DeliveryOutputRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    resolution: Literal["original", "1080p", "720p", "480p"]
    quality: Literal["high", "balanced", "compact"]


class DeliveryOutputResponse(BaseModel):
    name: str
    job: EncodingJobResponse


class DeliveryBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID
    created_at: datetime
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool
    outputs: list[DeliveryOutputResponse] = Field(default_factory=list)
