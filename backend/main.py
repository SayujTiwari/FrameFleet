from contextlib import asynccontextmanager
from math import ceil
import os
from pathlib import Path
from shutil import rmtree
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine, get_database_session
from backend.encoding_profiles import ENCODING_PROFILES, OUTPUT_HEIGHTS
from backend.models import EncodingJobResponse, ExportSettingsResponse
from backend.probe import MediaProbeError, probe_video
from backend.tables import (
    EncodingJobRecord,
    EncodingSegmentRecord,
    EncodingSettingsRecord,
    SegmentExecutionRecord,
)


def backfill_segment_executions() -> None:
    with SessionLocal() as session:
        missing_segments = session.execute(
            select(
                EncodingSegmentRecord.job_id,
                EncodingSegmentRecord.segment_index,
            )
            .outerjoin(
                SegmentExecutionRecord,
                (
                    SegmentExecutionRecord.job_id
                    == EncodingSegmentRecord.job_id
                )
                & (
                    SegmentExecutionRecord.segment_index
                    == EncodingSegmentRecord.segment_index
                ),
            )
            .where(SegmentExecutionRecord.job_id.is_(None))
        ).all()

        session.add_all(
            SegmentExecutionRecord(
                job_id=job_id,
                segment_index=segment_index,
                attempt_count=0,
            )
            for job_id, segment_index in missing_segments
        )
        session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    backfill_segment_executions()
    yield


app = FastAPI(title="FrameFleet API", lifespan=lifespan)

UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parent / "uploads"
UPLOAD_ROOT = Path(os.environ.get("FRAMEFLEET_UPLOAD_ROOT", str(DEFAULT_UPLOAD_ROOT)))

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


# get the nessacary info (helper)
def build_job_response(
    session: Session,
    job: EncodingJobRecord,
) -> EncodingJobResponse:
    completed_segments = session.scalar(
        select(func.count())
        .select_from(EncodingSegmentRecord)
        .where(
            EncodingSegmentRecord.job_id == job.job_id,
            EncodingSegmentRecord.status == "completed",
        )
    )
    settings = session.get(EncodingSettingsRecord, job.job_id)
    attempt_counts = session.scalars(
        select(SegmentExecutionRecord.attempt_count).where(
            SegmentExecutionRecord.job_id == job.job_id
        )
    ).all()

    return EncodingJobResponse.model_validate(job).model_copy(
        update={
            "completed_segments": completed_segments or 0,
            "retry_count": sum(max(0, count - 1) for count in attempt_counts),
            "export_settings": (
                ExportSettingsResponse.model_validate(settings)
                if settings is not None
                else None
            ),
        }
    )


@app.post("/jobs", status_code=201)
def create_encoding_job(
    video: Annotated[UploadFile, File()],
    target_segment_seconds: Annotated[float, Form(gt=0)] = 30,
    # quality choices
    output_resolution: Annotated[
        Literal["original", "1080p", "720p", "480p"],
        Form(),
    ] = "original",
    quality: Annotated[
        Literal["high", "balanced", "compact"],
        Form(),
    ] = "balanced",
    session: Session = Depends(get_database_session),
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

    segment_count = ceil(probe.duration_seconds / target_segment_seconds)

    # video format choices
    requested_height = OUTPUT_HEIGHTS[output_resolution]
    output_height = (
        min(requested_height, probe.height) if requested_height is not None else None
    )

    if output_height is not None:
        output_height -= output_height % 2

    profile = ENCODING_PROFILES[quality]
    job = EncodingJobRecord(
        job_id=job_id,
        status="ready",
        file_name=video.filename,
        source_path=str(source_path),
        file_size_bytes=file_size_bytes,
        duration_seconds=probe.duration_seconds,
        target_segment_seconds=target_segment_seconds,
        segment_count=segment_count,
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        format_name=probe.format_name,
        has_audio=probe.has_audio,
    )

    try:
        session.add(job)
        session.add(
            EncodingSettingsRecord(
                job_id=job_id,
                resolution=output_resolution,
                output_height=output_height,
                quality=quality,
                video_crf=profile.crf,
                encoding_preset=profile.preset,
            )
        )
        segments = [
            EncodingSegmentRecord(
                job_id=job_id,
                segment_index=index,
                status="pending",
                start_seconds=index * target_segment_seconds,
                end_seconds=min(
                    (index + 1) * target_segment_seconds,
                    probe.duration_seconds,
                ),
                output_path=None,
            )
            for index in range(segment_count)
        ]
        session.add_all(segments)
        session.add_all(
            SegmentExecutionRecord(
                job_id=job_id,
                segment_index=segment.segment_index,
                attempt_count=0,
            )
            for segment in segments
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        rmtree(source_path.parent, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Could not create the encoding job",
        ) from error

    return build_job_response(session, job)


@app.get("/jobs/{job_id}")
def get_encoding_job(
    job_id: UUID,
    session: Session = Depends(get_database_session),
) -> EncodingJobResponse:
    job = session.get(EncodingJobRecord, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return build_job_response(session, job)


@app.get("/jobs/{job_id}/download", response_class=FileResponse)
def download_encoding_job(
    job_id: UUID,
    session: Session = Depends(get_database_session),
) -> FileResponse:
    job = session.get(EncodingJobRecord, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Export is not ready")

    output_path = Path(job.source_path).parent / "output.mp4"

    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")

    original_stem = Path(job.file_name).stem or "video"
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"{original_stem}-framefleet.mp4",
    )
