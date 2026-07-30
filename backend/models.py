from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class EncodingJobResponse(BaseModel):
    job_id: UUID
    status: Literal["ready"]
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    target_segment_seconds: float
    segment_count: int
    width: int
    height: int
    video_codec: str
    format_name: str
    has_audio: bool
