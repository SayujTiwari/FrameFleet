from math import ceil
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.models import CreateEncodingJobRequest, EncodingJobResponse

app = FastAPI(title="FrameFleet API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=201)
def create_encoding_job(
    request: CreateEncodingJobRequest,
) -> EncodingJobResponse:
    segment_count = ceil(
        request.duration_seconds / request.target_segment_seconds
    )

    return EncodingJobResponse(
        job_id=uuid4(),
        status="planned",
        segment_count=segment_count,
    )
