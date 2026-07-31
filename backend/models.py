from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EncodingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    status: Literal["ready", "processing", "completed", "failed"]
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    target_segment_seconds: float
    segment_count: int
    completed_segments: int = 0
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool
