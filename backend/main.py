from collections.abc import Sequence
from contextlib import asynccontextmanager
import json
import logging
from math import ceil
import os
from pathlib import Path
from shutil import rmtree
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine, get_database_session
from backend.encoding_profiles import ENCODING_PROFILES, OUTPUT_HEIGHTS
from backend.models import (
    DeliveryBatchResponse,
    DeliveryOutputRequest,
    DeliveryOutputResponse,
    EncodingJobResponse,
    ExportSettingsResponse,
    ExportSizeConstraintResponse,
)
from backend.probe import MediaProbeError, VideoProbe, probe_video
from backend.size_constraints import SizeConstraintError, calculate_size_budget
from backend.tables import (
    DeliveryBatchRecord,
    DeliveryOutputRecord,
    EncodingConstraintRecord,
    EncodingJobRecord,
    EncodingOptimizationRecord,
    EncodingSegmentRecord,
    EncodingSettingsRecord,
    SegmentExecutionRecord,
)

LOGGER = logging.getLogger(__name__)


def backfill_segment_executions() -> None:
    with SessionLocal() as session:
        missing_segments = session.execute(
            select(
                EncodingSegmentRecord.job_id,
                EncodingSegmentRecord.segment_index,
            )
            .outerjoin(
                SegmentExecutionRecord,
                (SegmentExecutionRecord.job_id == EncodingSegmentRecord.job_id)
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


def backfill_encoding_optimizations() -> None:
    with SessionLocal() as session:
        constrained_job_ids = session.scalars(
            select(EncodingConstraintRecord.job_id)
            .outerjoin(
                EncodingOptimizationRecord,
                EncodingOptimizationRecord.job_id
                == EncodingConstraintRecord.job_id,
            )
            .where(EncodingOptimizationRecord.job_id.is_(None))
        ).all()

        session.add_all(
            EncodingOptimizationRecord(
                job_id=job_id,
                adjustment_count=0,
            )
            for job_id in constrained_job_ids
        )
        session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    backfill_segment_executions()
    backfill_encoding_optimizations()
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


# Build responses for several jobs without repeating the same queries per job.
def build_job_responses(
    session: Session,
    jobs: Sequence[EncodingJobRecord],
) -> list[EncodingJobResponse]:
    if not jobs:
        return []

    job_ids = [job.job_id for job in jobs]
    completed_segments_by_job = dict(
        session.execute(
            select(EncodingSegmentRecord.job_id, func.count())
            .where(
                EncodingSegmentRecord.job_id.in_(job_ids),
                EncodingSegmentRecord.status == "completed",
            )
            .group_by(EncodingSegmentRecord.job_id)
        ).all()
    )
    settings_by_job = {
        settings.job_id: settings
        for settings in session.scalars(
            select(EncodingSettingsRecord).where(
                EncodingSettingsRecord.job_id.in_(job_ids)
            )
        ).all()
    }
    constraints_by_job = {
        constraint.job_id: constraint
        for constraint in session.scalars(
            select(EncodingConstraintRecord).where(
                EncodingConstraintRecord.job_id.in_(job_ids)
            )
        ).all()
    }
    optimizations_by_job = {
        optimization.job_id: optimization
        for optimization in session.scalars(
            select(EncodingOptimizationRecord).where(
                EncodingOptimizationRecord.job_id.in_(job_ids)
            )
        ).all()
    }
    delivery_outputs_by_job = {
        output.job_id: output
        for output in session.scalars(
            select(DeliveryOutputRecord).where(
                DeliveryOutputRecord.job_id.in_(job_ids)
            )
        ).all()
    }
    retry_counts_by_job = dict.fromkeys(job_ids, 0)

    attempt_counts = session.execute(
        select(
            SegmentExecutionRecord.job_id,
            SegmentExecutionRecord.attempt_count,
        ).where(SegmentExecutionRecord.job_id.in_(job_ids))
    ).all()

    for job_id, attempt_count in attempt_counts:
        optimization = optimizations_by_job.get(job_id)
        adjustment_count = (
            optimization.adjustment_count if optimization is not None else 0
        )
        retry_counts_by_job[job_id] += max(
            0,
            attempt_count - 1 - adjustment_count,
        )

    responses = []

    for job in jobs:
        settings = settings_by_job.get(job.job_id)
        constraint = constraints_by_job.get(job.job_id)
        optimization = optimizations_by_job.get(job.job_id)
        delivery_output = delivery_outputs_by_job.get(job.job_id)
        output_directory = (
            Path(delivery_output.output_directory)
            if delivery_output is not None
            else Path(job.source_path).parent
        )
        output_path = output_directory / "output.mp4"

        try:
            output_file_size_bytes = (
                output_path.stat().st_size
                if job.status == "completed"
                else None
            )
        except OSError:
            output_file_size_bytes = None

        responses.append(
            EncodingJobResponse.model_validate(job).model_copy(
                update={
                    "completed_segments": completed_segments_by_job.get(
                        job.job_id,
                        0,
                    ),
                    "retry_count": retry_counts_by_job[job.job_id],
                    "export_settings": (
                        ExportSettingsResponse.model_validate(settings)
                        if settings is not None
                        else None
                    ),
                    "size_constraint": (
                        ExportSizeConstraintResponse.model_validate(
                            constraint
                        ).model_copy(
                            update={
                                "adjustment_count": (
                                    optimization.adjustment_count
                                    if optimization is not None
                                    else 0
                                ),
                                "last_output_size_bytes": (
                                    optimization.last_output_size_bytes
                                    if optimization is not None
                                    else None
                                ),
                            }
                        )
                        if constraint is not None
                        else None
                    ),
                    "output_file_size_bytes": output_file_size_bytes,
                }
            )
        )

    return responses


def build_job_response(
    session: Session,
    job: EncodingJobRecord,
) -> EncodingJobResponse:
    return build_job_responses(session, [job])[0]


def add_encoding_job_records(
    session: Session,
    *,
    job_id: UUID,
    file_name: str,
    source_path: Path,
    file_size_bytes: int,
    probe: VideoProbe,
    target_segment_seconds: float,
    output_resolution: Literal["original", "1080p", "720p", "480p"],
    quality: Literal["high", "balanced", "compact"],
    max_file_size_mb: float | None = None,
) -> EncodingJobRecord:
    segment_count = ceil(probe.duration_seconds / target_segment_seconds)
    requested_height = OUTPUT_HEIGHTS[output_resolution]
    output_height = (
        min(requested_height, probe.height) if requested_height is not None else None
    )

    if output_height is not None:
        output_height -= output_height % 2

    # all the records below
    profile = ENCODING_PROFILES[quality]
    job = EncodingJobRecord(
        job_id=job_id,
        status="ready",
        file_name=file_name,
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
    settings = EncodingSettingsRecord(
        job_id=job_id,
        resolution=output_resolution,
        output_height=output_height,
        quality=quality,
        video_crf=profile.crf,
        encoding_preset=profile.preset,
    )
    size_budget = (
        calculate_size_budget(
            duration_seconds=probe.duration_seconds,
            max_file_size_mb=max_file_size_mb,
            has_audio=probe.has_audio,
        )
        if max_file_size_mb is not None
        else None
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

    # Insert the parent job before its settings, constraints, and segments.
    # A flush sends SQL without committing, so a later rollback remains atomic.
    session.add(job)
    session.flush()
    session.add(settings)

    if size_budget is not None:
        session.add_all(
            [
                EncodingConstraintRecord(
                    job_id=job_id,
                    target_size_bytes=size_budget.target_size_bytes,
                    video_bitrate_bps=size_budget.video_bitrate_bps,
                    audio_bitrate_bps=size_budget.audio_bitrate_bps,
                ),
                EncodingOptimizationRecord(
                    job_id=job_id,
                    adjustment_count=0,
                ),
            ]
        )

    session.add_all(segments)
    session.add_all(
        SegmentExecutionRecord(
            job_id=job_id,
            segment_index=segment.segment_index,
            attempt_count=0,
        )
        for segment in segments
    )
    return job


# convert JSON to python objects and checks
def parse_delivery_outputs(raw_outputs: str) -> list[DeliveryOutputRequest]:
    try:
        document = json.loads(raw_outputs)

        if not isinstance(document, list):
            raise ValueError

        outputs = [DeliveryOutputRequest.model_validate(item) for item in document]
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="Outputs must be a valid JSON array of delivery settings",
        ) from error

    if not 1 <= len(outputs) <= 6:
        raise HTTPException(
            status_code=422,
            detail="A delivery batch must contain between 1 and 6 outputs",
        )

    normalized_names = [output.name.casefold() for output in outputs]

    if len(set(normalized_names)) != len(normalized_names):
        raise HTTPException(
            status_code=422,
            detail="Every delivery output must have a unique name",
        )

    configurations = [(output.resolution, output.quality) for output in outputs]

    if len(set(configurations)) != len(configurations):
        raise HTTPException(
            status_code=422,
            detail="Every delivery output must use a unique configuration",
        )

    return outputs


# load every output belonging to a batch
def build_delivery_batch_response(
    session: Session,
    batch: DeliveryBatchRecord,
) -> DeliveryBatchResponse:
    output_records = session.scalars(
        select(DeliveryOutputRecord)
        .where(DeliveryOutputRecord.batch_id == batch.batch_id)
        .order_by(DeliveryOutputRecord.position)
    ).all()
    jobs = session.scalars(
        select(EncodingJobRecord).where(
            EncodingJobRecord.job_id.in_([output.job_id for output in output_records])
        )
    ).all()
    jobs_by_id = {
        job.job_id: response
        for job, response in zip(
            jobs,
            build_job_responses(session, jobs),
            strict=True,
        )
    }

    return DeliveryBatchResponse.model_validate(batch).model_copy(
        update={
            "outputs": [
                DeliveryOutputResponse(
                    name=output.name,
                    job=jobs_by_id[output.job_id],
                )
                for output in output_records
            ]
        }
    )


@app.post("/deliveries", status_code=201)
def create_delivery_batch(
    video: Annotated[UploadFile, File()],
    outputs: Annotated[str, Form()],
    target_segment_seconds: Annotated[float, Form(gt=0)] = 30,
    session: Session = Depends(get_database_session),
) -> DeliveryBatchResponse:
    # validations
    if not video.filename:
        raise HTTPException(status_code=400, detail="Video must have a filename")

    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=415, detail="File must be a video")

    requested_outputs = parse_delivery_outputs(outputs)
    batch_id = uuid4()
    source_path, file_size_bytes = save_upload(
        video,
        UPLOAD_ROOT / str(batch_id),
    )

    try:
        probe = probe_video(source_path)
    except MediaProbeError as error:
        rmtree(source_path.parent, ignore_errors=True)
        raise HTTPException(status_code=415, detail=str(error)) from error

    batch = DeliveryBatchRecord(
        batch_id=batch_id,
        file_name=video.filename,
        source_path=str(source_path),
        file_size_bytes=file_size_bytes,
        duration_seconds=probe.duration_seconds,
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        format_name=probe.format_name,
        has_audio=probe.has_audio,
    )

    try:
        session.add(batch)
        output_records = []

        for position, requested_output in enumerate(requested_outputs):
            job_id = uuid4()
            # each gets seperate directory
            output_directory = source_path.parent / "outputs" / str(job_id)
            output_directory.mkdir(parents=True, exist_ok=False)
            add_encoding_job_records(
                session,
                job_id=job_id,
                file_name=video.filename,
                source_path=source_path,
                file_size_bytes=file_size_bytes,
                probe=probe,
                target_segment_seconds=target_segment_seconds,
                output_resolution=requested_output.resolution,
                quality=requested_output.quality,
                max_file_size_mb=requested_output.max_file_size_mb,
            )
            output_records.append(
                DeliveryOutputRecord(
                    job_id=job_id,
                    batch_id=batch_id,
                    name=requested_output.name,
                    position=position,
                    output_directory=str(output_directory),
                )
            )

        # Flush parent jobs before inserting the association records that
        # reference them. Everything still belongs to the same transaction.
        session.flush()
        session.add_all(output_records)
        session.commit()
    except SizeConstraintError as error:
        session.rollback()
        rmtree(source_path.parent, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, SQLAlchemyError) as error:
        session.rollback()
        rmtree(source_path.parent, ignore_errors=True)
        LOGGER.exception("Could not create delivery batch")
        raise HTTPException(
            status_code=500,
            detail="Could not create the delivery batch",
        ) from error

    return build_delivery_batch_response(session, batch)


@app.get("/deliveries/{batch_id}")
def get_delivery_batch(
    batch_id: UUID,
    session: Session = Depends(get_database_session),
) -> DeliveryBatchResponse:
    batch = session.get(DeliveryBatchRecord, batch_id)

    if batch is None:
        raise HTTPException(status_code=404, detail="Delivery batch not found")

    return build_delivery_batch_response(session, batch)


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

    try:
        job = add_encoding_job_records(
            session,
            job_id=job_id,
            file_name=video.filename,
            source_path=source_path,
            file_size_bytes=file_size_bytes,
            probe=probe,
            target_segment_seconds=target_segment_seconds,
            output_resolution=output_resolution,
            quality=quality,
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


@app.get("/jobs")
def list_encoding_jobs(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    session: Session = Depends(get_database_session),
) -> list[EncodingJobResponse]:
    jobs = session.scalars(
        select(EncodingJobRecord)
        .order_by(EncodingJobRecord.created_at.desc())
        .limit(limit)
    ).all()

    return build_job_responses(session, jobs)


@app.get("/jobs/{job_id}")
def get_encoding_job(
    job_id: UUID,
    session: Session = Depends(get_database_session),
) -> EncodingJobResponse:
    job = session.get(EncodingJobRecord, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return build_job_response(session, job)


@app.post("/jobs/{job_id}/cancel")
def cancel_encoding_job(
    job_id: UUID,
    session: Session = Depends(get_database_session),
) -> EncodingJobResponse:
    existing_job = session.get(EncodingJobRecord, job_id)

    if existing_job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    executions = session.scalars(
        select(SegmentExecutionRecord)
        .where(SegmentExecutionRecord.job_id == job_id)
        .with_for_update()
    ).all()
    job = session.scalar(
        select(EncodingJobRecord)
        .where(EncodingJobRecord.job_id == job_id)
        .with_for_update()
    )

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "cancelled":
        return build_job_response(session, job)

    if job.status in {"completed", "failed", "assembling"}:
        raise HTTPException(
            status_code=409,
            detail=f"A {job.status} job cannot be cancelled",
        )

    session.execute(
        update(EncodingSegmentRecord)
        .where(
            EncodingSegmentRecord.job_id == job_id,
            EncodingSegmentRecord.status.in_(["pending", "processing"]),
        )
        .values(status="cancelled")
    )

    for execution in executions:
        execution.leased_by = None
        execution.lease_expires_at = None

    job.status = "cancelled"
    session.commit()
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

    delivery_output = session.get(DeliveryOutputRecord, job_id)
    output_directory = (
        Path(delivery_output.output_directory)
        if delivery_output is not None
        else Path(job.source_path).parent
    )
    output_path = output_directory / "output.mp4"

    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")

    original_stem = Path(job.file_name).stem or "video"
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"{original_stem}-framefleet.mp4",
    )
