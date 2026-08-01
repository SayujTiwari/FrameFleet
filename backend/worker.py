from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.tables import (
    EncodingJobRecord,
    EncodingSegmentRecord,
    EncodingSettingsRecord,
)

POLL_INTERVAL_SECONDS = 1


@dataclass(frozen=True)
class ClaimedSegment:
    job_id: UUID
    segment_index: int
    source_path: Path
    start_seconds: float
    end_seconds: float
    output_height: int | None
    video_crf: int
    encoding_preset: str


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
    settings = session.get(EncodingSettingsRecord, segment.job_id)

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
        output_height=settings.output_height if settings else None,
        video_crf=settings.video_crf if settings else 23,
        encoding_preset=settings.encoding_preset if settings else "veryfast",
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
        "-vf",
        (
            f"scale=-2:{segment.output_height}"
            if segment.output_height is not None
            else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
        "-c:v",
        "libx264",
        "-crf",
        str(segment.video_crf),
        "-preset",
        segment.encoding_preset,
        "-pix_fmt",
        "yuv420p",
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
) -> bool:

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
            return False

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
            job.status = "assembling"
        else:
            job.status = "processing"

        session.commit()
        return job.status == "assembling"


#
def assemble_job(job_id: UUID) -> Path:
    # load job and segments
    with SessionLocal() as session:
        job = session.get(EncodingJobRecord, job_id)
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

    job_directory = Path(job.source_path).parent
    manifest_path = job_directory / "segments.txt"
    output_path = job_directory / "output.mp4"
    temporary_path = job_directory / "output.tmp.mp4"

    # convert them into path objects
    paths = [Path(path) for path in segment_paths if path is not None]

    if len(paths) != job.segment_count or not all(path.is_file() for path in paths):
        raise EncodingError("An encoded segment file is missing")

    # to pass into FFmpeg
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
        "-t",
        str(job.duration_seconds),
        "-movflags",
        "+faststart",
        "-y",
        str(temporary_path),
    ]

    # run FFmpeg
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

    temporary_path.replace(output_path)  # move into place
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

    label = f"{segment.job_id}/{segment.segment_index}"
    print(f"Encoding segment {label}", flush=True)

    try:
        output_path = encode_segment(segment)
    except EncodingError as error:
        print(f"Segment {label} failed: {error}", flush=True)
        finish_segment(segment, "failed")
        return True

    should_assemble = finish_segment(segment, "completed", output_path)
    print(f"Segment {label} completed", flush=True)

    if should_assemble:
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
    print("FrameFleet worker started", flush=True)

    while True:
        if not process_next_segment():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_worker()
