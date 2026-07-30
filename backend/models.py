from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class EncodingJobResponse(BaseModel):
    job_id: UUID
    status: Literal["uploaded"]
    file_name: str
    file_size_bytes: int
    duration_seconds: float
    target_segment_seconds: float
    segment_count: int
