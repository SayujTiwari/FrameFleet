from dataclasses import dataclass
from math import ceil
import os
from pathlib import Path
from shutil import rmtree
from threading import Lock
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.models import EncodingJobResponse
from backend.probe import MediaProbeError, probe_video

app = FastAPI(title="FrameFleet API")

UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parent / "uploads"
UPLOAD_ROOT = Path(
    os.environ.get("FRAMEFLEET_UPLOAD_ROOT", str(DEFAULT_UPLOAD_ROOT))
)


@dataclass(frozen=True)
class StoredJob:
    response: EncodingJobResponse
    source_path: Path


jobs: dict[UUID, StoredJob] = {}
jobs_lock = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def save_upload(upload: UploadFile, job_directory: Path) -> tuple[Path, int]:
    source_path = job_directory / "source"
    total_bytes = 0

    try:
        job_directory.mkdir(parents=True, exist_ok=False)

        with source_path.open("xb") as destination:
            while chunk := upload.file.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)

                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Video exceeds the 2 GiB upload limit",
                    )

                destination.write(chunk)

        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Video is empty")

        return source_path, total_bytes
    except HTTPException:
        rmtree(job_directory, ignore_errors=True)
        raise
    except OSError as error:
        rmtree(job_directory, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Could not store the uploaded video",
        ) from error
    finally:
        upload.file.close()


@app.post("/jobs", status_code=201)
def create_encoding_job(
    video: Annotated[UploadFile, File()],
    target_segment_seconds: Annotated[float, Form(gt=0)] = 30,
) -> EncodingJobResponse:
    if not video.filename:
        raise HTTPException(status_code=400, detail="Video must have a filename")

    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=415, detail="File must be a video")

    job_id = uuid4()
    source_path, file_size_bytes = save_upload(
        video,
        UPLOAD_ROOT / str(job_id),
    )

    try:
        probe = probe_video(source_path)
    except MediaProbeError as error:
        rmtree(source_path.parent, ignore_errors=True)
        raise HTTPException(status_code=415, detail=str(error)) from error

    job = EncodingJobResponse(
        job_id=job_id,
        status="ready",
        file_name=video.filename,
        file_size_bytes=file_size_bytes,
        duration_seconds=probe.duration_seconds,
        target_segment_seconds=target_segment_seconds,
        segment_count=ceil(probe.duration_seconds / target_segment_seconds),
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        format_name=probe.format_name,
        has_audio=probe.has_audio,
    )

    with jobs_lock:
        jobs[job.job_id] = StoredJob(
            response=job,
            source_path=source_path,
        )

    return job


@app.get("/jobs/{job_id}")
def get_encoding_job(job_id: UUID) -> EncodingJobResponse:
    with jobs_lock:
        stored_job = jobs.get(job_id)

    if stored_job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return stored_job.response
