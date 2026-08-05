from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
import socket
import subprocess
import time
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.tables import (
    DeliveryOutputRecord,
    EncodingConstraintRecord,
    EncodingJobRecord,
    EncodingSegmentRecord,
    EncodingSettingsRecord,
    SegmentExecutionRecord,
)

# Global
POLL_INTERVAL_SECONDS = 1
LEASE_DURATION_SECONDS = max(
    3,
    int(os.environ.get("FRAMEFLEET_LEASE_SECONDS", "15")),
)
HEARTBEAT_INTERVAL_SECONDS = max(1, LEASE_DURATION_SECONDS // 3)
MAX_ATTEMPTS = max(1, int(os.environ.get("FRAMEFLEET_MAX_ATTEMPTS", "3")))
WORKER_ID = os.environ.get("FRAMEFLEET_WORKER_ID", socket.gethostname())


# working on this
@dataclass(frozen=True)
class ClaimedSegment:
    job_id: UUID
    segment_index: int
    source_path: Path
    output_directory: Path
    start_seconds: float
    end_seconds: float
    output_height: int | None
    video_crf: int
    encoding_preset: str
    target_video_bitrate_bps: int | None
    attempt_number: int
    worker_id: str
    reclaimed: bool


@dataclass(frozen=True)
class CompletionResult:
    accepted: bool
    should_assemble: bool


class EncodingError(Exception):
    pass


# needed to sync workers even if on diff computers
def database_time(session: Session) -> datetime:
    current_time = session.scalar(select(func.now()))

    if current_time is None:
        raise RuntimeError("Database did not return its current time")

    return current_time


def claim_next_segment(session: Session) -> ClaimedSegment | None:
    now = database_time(session)
    # get the earliest segment that belongs to a job and is still active
    statement = (
        select(EncodingSegmentRecord, SegmentExecutionRecord)
        .join(
            SegmentExecutionRecord,
            (SegmentExecutionRecord.job_id == EncodingSegmentRecord.job_id)
            & (
                SegmentExecutionRecord.segment_index
                == EncodingSegmentRecord.segment_index
            ),
        )
        .join(
            EncodingJobRecord,
            EncodingJobRecord.job_id == EncodingSegmentRecord.job_id,
        )
        .where(
            EncodingJobRecord.status.not_in(
                ["failed", "completed", "assembling", "cancelled"]
            ),
            or_(
                EncodingSegmentRecord.status == "pending",
                and_(
                    EncodingSegmentRecord.status == "processing",
                    or_(
                        SegmentExecutionRecord.lease_expires_at.is_(None),
                        SegmentExecutionRecord.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .order_by(
            EncodingJobRecord.created_at,
            EncodingSegmentRecord.segment_index,
        )
        # race condition
        .with_for_update(
            skip_locked=True,
            of=(
                EncodingSegmentRecord.__table__,
                SegmentExecutionRecord.__table__,
            ),
        )
        .limit(1)
    )
    row = session.execute(statement).first()

    if row is None:
        return None

    segment, execution = row
    job = session.get(EncodingJobRecord, segment.job_id)
    settings = session.get(EncodingSettingsRecord, segment.job_id)
    constraint = session.get(EncodingConstraintRecord, segment.job_id)
    delivery_output = session.get(DeliveryOutputRecord, segment.job_id)

    if job is None:
        return None

    reclaimed = segment.status == "processing"
    execution.attempt_count += 1
    execution.leased_by = WORKER_ID
    execution.lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)
    segment.status = "processing"
    job.status = "processing"
    session.commit()

    return ClaimedSegment(
        job_id=job.job_id,
        segment_index=segment.segment_index,
        source_path=Path(job.source_path),
        output_directory=(
            Path(delivery_output.output_directory)
            if delivery_output is not None
            else Path(job.source_path).parent
        ),
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        output_height=settings.output_height if settings else None,
        video_crf=settings.video_crf if settings else 23,
        encoding_preset=settings.encoding_preset if settings else "veryfast",
        target_video_bitrate_bps=(
            constraint.video_bitrate_bps if constraint is not None else None
        ),
        attempt_number=execution.attempt_count,
        worker_id=WORKER_ID,
        reclaimed=reclaimed,
    )


# ensure worker and attempt are synced to keep outputs matched
def owns_attempt(
    execution: SegmentExecutionRecord,
    segment: ClaimedSegment,
) -> bool:
    return (
        execution.leased_by == segment.worker_id
        and execution.attempt_count == segment.attempt_number
    )


# incase the processing takes very long
def renew_lease(segment: ClaimedSegment) -> bool:
    with SessionLocal() as session:
        # retrieve the lock and record
        execution = session.scalar(
            select(SegmentExecutionRecord)
            .where(
                SegmentExecutionRecord.job_id == segment.job_id,
                SegmentExecutionRecord.segment_index == segment.segment_index,
            )
            .with_for_update()  # temp lock
        )

        if execution is None or not owns_attempt(execution, segment):
            return False

        execution.lease_expires_at = database_time(session) + timedelta(
            seconds=LEASE_DURATION_SECONDS
        )
        session.commit()
        return True


# runs ffmpeg in intervals-renewing lease
def run_ffmpeg_with_heartbeat(
    command: list[str],
    segment: ClaimedSegment,
) -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise EncodingError("FFmpeg could not be started") from error

    while True:
        try:
            _, stderr = process.communicate(timeout=HEARTBEAT_INTERVAL_SECONDS)
            return process.returncode, stderr or ""
        except subprocess.TimeoutExpired:
            if renew_lease(segment):
                continue

            process.terminate()

            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

            raise EncodingError("The worker lost its segment lease")


def encode_segment(segment: ClaimedSegment) -> Path:
    output_directory = segment.output_directory / "segments"
    output_directory.mkdir(exist_ok=True)

    prefix = f"segment-{segment.segment_index:05d}"
    temporary_path = (
        output_directory / f"{prefix}.attempt-{segment.attempt_number}.tmp.mkv"
    )

    for stale_path in output_directory.glob(f"{prefix}.attempt-*.tmp.mkv"):
        stale_path.unlink(missing_ok=True)

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        str(segment.start_seconds),
        "-i",
        str(segment.source_path),
        "-t",
        str(segment.end_seconds - segment.start_seconds),
        "-map",
        "0:v:0",
        "-vf",
        (
            f"scale=-2:{segment.output_height}"
            if segment.output_height is not None
            else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
        "-c:v",
        "libx264",
    ]

    if segment.target_video_bitrate_bps is not None:
        command.extend(
            [
                "-b:v",
                str(segment.target_video_bitrate_bps),
                "-maxrate",
                str(round(segment.target_video_bitrate_bps * 1.25)),
                "-bufsize",
                str(segment.target_video_bitrate_bps * 2),
            ]
        )
    else:
        command.extend(["-crf", str(segment.video_crf)])

    command.extend(
        [
            "-preset",
            segment.encoding_preset,
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(temporary_path),
        ]
    )

    try:
        return_code, stderr = run_ffmpeg_with_heartbeat(command, segment)
    except EncodingError:
        temporary_path.unlink(missing_ok=True)
        raise

    if return_code != 0 or not temporary_path.exists():
        temporary_path.unlink(missing_ok=True)
        message = stderr.strip() or "FFmpeg produced no output"
        raise EncodingError(message)

    return temporary_path


def finish_segment_success(
    segment: ClaimedSegment,
    temporary_path: Path,
) -> CompletionResult:
    with SessionLocal() as session:
        execution = session.scalar(
            select(SegmentExecutionRecord)
            .where(
                SegmentExecutionRecord.job_id == segment.job_id,
                SegmentExecutionRecord.segment_index == segment.segment_index,
            )
            .with_for_update()
        )
        record = session.get(
            EncodingSegmentRecord,
            (segment.job_id, segment.segment_index),
        )
        job = session.scalar(
            select(EncodingJobRecord)
            .where(EncodingJobRecord.job_id == segment.job_id)
            .with_for_update()
        )
        # ensure ownership before publishing
        if (
            execution is None
            or record is None
            or job is None
            or not owns_attempt(execution, segment)
        ):
            temporary_path.unlink(missing_ok=True)
            return CompletionResult(accepted=False, should_assemble=False)

        output_path = (
            segment.output_directory
            / "segments"
            / f"segment-{segment.segment_index:05d}.mkv"
        )

        try:
            temporary_path.replace(output_path)
        except OSError as error:
            raise EncodingError("Could not publish the encoded segment") from error

        record.status = "completed"
        record.output_path = str(output_path)
        execution.leased_by = None
        execution.lease_expires_at = None

        failed_count = session.scalar(
            select(func.count())
            .select_from(EncodingSegmentRecord)
            .where(
                EncodingSegmentRecord.job_id == segment.job_id,
                EncodingSegmentRecord.status == "failed",
            )
        )
        completed_count = session.scalar(
            select(func.count())
            .select_from(EncodingSegmentRecord)
            .where(
                EncodingSegmentRecord.job_id == segment.job_id,
                EncodingSegmentRecord.status == "completed",
            )
        )

        if failed_count:
            job.status = "failed"
        elif completed_count == job.segment_count:
            job.status = "assembling"
        else:
            job.status = "processing"

        session.commit()
        return CompletionResult(
            accepted=True,
            should_assemble=job.status == "assembling",
        )


# either retry, failed or ignored (stale worker)
def finish_segment_failure(segment: ClaimedSegment, error: str) -> str:
    with SessionLocal() as session:
        execution = session.scalar(
            select(SegmentExecutionRecord)
            .where(
                SegmentExecutionRecord.job_id == segment.job_id,
                SegmentExecutionRecord.segment_index == segment.segment_index,
            )
            .with_for_update()
        )
        record = session.get(
            EncodingSegmentRecord,
            (segment.job_id, segment.segment_index),
        )
        job = session.scalar(
            select(EncodingJobRecord)
            .where(EncodingJobRecord.job_id == segment.job_id)
            .with_for_update()
        )

        if (
            execution is None
            or record is None
            or job is None
            or not owns_attempt(execution, segment)
        ):
            return "stale"

        execution.last_error = error[:1000]
        execution.leased_by = None
        execution.lease_expires_at = None

        another_segment_failed = bool(
            session.scalar(
                select(func.count())
                .select_from(EncodingSegmentRecord)
                .where(
                    EncodingSegmentRecord.job_id == segment.job_id,
                    EncodingSegmentRecord.status == "failed",
                )
            )
        )

        if (
            execution.attempt_count < MAX_ATTEMPTS
            and not another_segment_failed
            and job.status != "failed"
        ):
            record.status = "pending"
            job.status = "processing"
            outcome = "retrying"
        else:
            record.status = "failed"
            job.status = "failed"
            outcome = "failed"

        session.commit()
        return outcome


def assemble_job(job_id: UUID) -> Path:
    with SessionLocal() as session:
        job = session.get(EncodingJobRecord, job_id)
        delivery_output = session.get(DeliveryOutputRecord, job_id)
        constraint = session.get(EncodingConstraintRecord, job_id)
        segment_paths = session.scalars(
            select(EncodingSegmentRecord.output_path)
            .where(
                EncodingSegmentRecord.job_id == job_id,
                EncodingSegmentRecord.status == "completed",
            )
            .order_by(EncodingSegmentRecord.segment_index)
        ).all()

    if job is None or len(segment_paths) != job.segment_count:
        raise EncodingError("Not all encoded segments are available")

    job_directory = (
        Path(delivery_output.output_directory)
        if delivery_output is not None
        else Path(job.source_path).parent
    )
    manifest_path = job_directory / "segments.txt"
    output_path = job_directory / "output.mp4"
    temporary_path = job_directory / "output.tmp.mp4"
    paths = [Path(path) for path in segment_paths if path is not None]

    if len(paths) != job.segment_count or not all(path.is_file() for path in paths):
        raise EncodingError("An encoded segment file is missing")

    manifest_path.write_text(
        "".join(f"file '{path}'\n" for path in paths),
        encoding="utf-8",
    )
    temporary_path.unlink(missing_ok=True)

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest_path),
        "-i",
        str(job.source_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
    ]

    if constraint is not None and constraint.audio_bitrate_bps > 0:
        command.extend(["-b:a", str(constraint.audio_bitrate_bps)])

    command.extend(
        [
            "-t",
            str(job.duration_seconds),
            "-movflags",
            "+faststart",
            "-y",
            str(temporary_path),
        ]
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise EncodingError("FFmpeg could not assemble the export") from error
    finally:
        manifest_path.unlink(missing_ok=True)

    if result.returncode != 0 or not temporary_path.exists():
        temporary_path.unlink(missing_ok=True)
        message = result.stderr.strip() or "FFmpeg produced no final export"
        raise EncodingError(message)

    temporary_path.replace(output_path)
    return output_path


def finish_assembly(job_id: UUID, status: str) -> None:
    with SessionLocal() as session:
        job = session.scalar(
            select(EncodingJobRecord)
            .where(EncodingJobRecord.job_id == job_id)
            .with_for_update()
        )

        if job is None:
            return

        job.status = status
        session.commit()


def process_next_segment() -> bool:
    with SessionLocal() as session:
        segment = claim_next_segment(session)

    if segment is None:
        return False

    label = (
        f"{segment.job_id}/{segment.segment_index} " f"attempt {segment.attempt_number}"
    )
    action = "Reclaiming" if segment.reclaimed else "Encoding"
    print(f"{action} segment {label}", flush=True)

    try:
        temporary_path = encode_segment(segment)
        completion = finish_segment_success(segment, temporary_path)
    except EncodingError as error:
        outcome = finish_segment_failure(segment, str(error))
        print(f"Segment {label} failed ({outcome}): {error}", flush=True)
        return True

    if not completion.accepted:
        print(f"Ignored stale result for segment {label}", flush=True)
        return True

    print(f"Segment {label} completed", flush=True)

    if completion.should_assemble:
        print(f"Assembling job {segment.job_id}", flush=True)

        try:
            final_path = assemble_job(segment.job_id)
        except EncodingError as error:
            print(f"Job {segment.job_id} assembly failed: {error}", flush=True)
            finish_assembly(segment.job_id, "failed")
            return True

        finish_assembly(segment.job_id, "completed")
        print(f"Job {segment.job_id} completed at {final_path}", flush=True)

    return True


def run_worker() -> None:
    print(
        f"FrameFleet worker {WORKER_ID} started "
        f"(lease={LEASE_DURATION_SECONDS}s, attempts={MAX_ATTEMPTS})",
        flush=True,
    )

    while True:
        if not process_next_segment():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_worker()
