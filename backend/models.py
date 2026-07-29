from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateEncodingJobRequest(BaseModel):
    file_name: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    target_segment_seconds: float = Field(default=30, gt=0)


class EncodingJobResponse(BaseModel):
    job_id: UUID
    status: Literal["planned"]
    segment_count: int
