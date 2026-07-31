from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.tables import EncodingJobRecord, EncodingSegmentRecord

POLL_INTERVAL_SECONDS = 1


@dataclass(frozen=True)
class ClaimedSegment:
    job_id: UUID
    segment_index: int
    source_path: Path
    start_seconds: float
    end_seconds: float


class EncodingError(Exception):
    pass


def claim_next_segment(session: Session) -> ClaimedSegment | None:
    # lock pending segement to worker
    statement = (
        select(EncodingSegmentRecord)
        .where(EncodingSegmentRecord.status == "pending")
        .order_by(
            EncodingSegmentRecord.job_id,
            EncodingSegmentRecord.segment_index,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    segment = session.scalar(statement)  # execute

    if segment is None:
        return None

    job = session.get(EncodingJobRecord, segment.job_id)

    if job is None:
        return None

    segment.status = "processing"
    job.status = "processing"
    session.commit()

    # send info of the segment
    return ClaimedSegment(
        job_id=job.job_id,
        segment_index=segment.segment_index,
        source_path=Path(job.source_path),
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
    )


def encode_segment(segment: ClaimedSegment) -> Path:
    output_directory = segment.source_path.parent / "segments"
    output_directory.mkdir(exist_ok=True)

    output_path = output_directory / f"segment-{segment.segment_index:05d}.mkv"
    temporary_path = output_directory / f"segment-{segment.segment_index:05d}.tmp.mkv"
    temporary_path.unlink(missing_ok=True)

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
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-y",
        str(temporary_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise EncodingError("FFmpeg could not be started") from error

    if result.returncode != 0 or not temporary_path.exists():
        temporary_path.unlink(missing_ok=True)
        message = result.stderr.strip() or "FFmpeg produced no output"
        raise EncodingError(message)

    temporary_path.replace(output_path)
    return output_path


def finish_segment(
    segment: ClaimedSegment,
    status: str,
    output_path: Path | None = None,
) -> None:

    # look up segment
    with SessionLocal() as session:
        record = session.get(
            EncodingSegmentRecord,
            (segment.job_id, segment.segment_index),
        )
        job = session.scalar(
            select(EncodingJobRecord)
            .where(EncodingJobRecord.job_id == segment.job_id)
            .with_for_update()  # prevent race condition
        )

        if record is None or job is None:
            return

        record.status = status
        record.output_path = str(output_path) if output_path else None

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
            job.status = "completed"
        else:
            job.status = "processing"

        session.commit()


def process_next_segment() -> bool:
    with SessionLocal() as session:
        segment = claim_next_segment(session)

    if segment is None:
        return False

    label = f"{segment.job_id}/{segment.segment_index}"
    print(f"Encoding segment {label}", flush=True)

    try:
        output_path = encode_segment(segment)
    except EncodingError as error:
        print(f"Segment {label} failed: {error}", flush=True)
        finish_segment(segment, "failed")
        return True

    finish_segment(segment, "completed", output_path)
    print(f"Segment {label} completed", flush=True)
    return True


def run_worker() -> None:
    print("FrameFleet worker started", flush=True)

    while True:
        if not process_next_segment():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_worker()
