from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database import Base

# models representing SQL database tables


# each job deetails
class EncodingJobRecord(Base):
    __tablename__ = "encoding_jobs"

    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    file_name: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(String(500))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float] = mapped_column(Float)
    target_segment_seconds: Mapped[float] = mapped_column(Float)
    segment_count: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(String(50))
    format_name: Mapped[str] = mapped_column(String(100))
    has_audio: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


# One uploaded master video that can produce several encoding jobs.
class DeliveryBatchRecord(Base):
    __tablename__ = "delivery_batches"

    batch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(String(500))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(String(50))
    format_name: Mapped[str] = mapped_column(String(100))
    has_audio: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


# Connects each requested delivery output to its existing encoding job.
class DeliveryOutputRecord(Base):
    __tablename__ = "delivery_outputs"

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("encoding_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("delivery_batches.batch_id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    output_directory: Mapped[str] = mapped_column(String(500))


# each segment details
class EncodingSegmentRecord(Base):
    __tablename__ = "encoding_segments"

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("encoding_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    segment_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


# # Per-job encoding and export settings
class EncodingSettingsRecord(Base):
    __tablename__ = "encoding_settings"

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("encoding_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    resolution: Mapped[str] = mapped_column(String(32))
    output_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[str] = mapped_column(String(32))
    video_crf: Mapped[int] = mapped_column(Integer)
    encoding_preset: Mapped[str] = mapped_column(String(32))


# Optional final-size budget for an encoding job.
class EncodingConstraintRecord(Base):
    __tablename__ = "encoding_constraints"

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("encoding_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_size_bytes: Mapped[int] = mapped_column(BigInteger)
    video_bitrate_bps: Mapped[int] = mapped_column(BigInteger)
    audio_bitrate_bps: Mapped[int] = mapped_column(Integer)


# Lease and retry state kept separately
class SegmentExecutionRecord(Base):
    __tablename__ = "segment_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "segment_index"],
            ["encoding_segments.job_id", "encoding_segments.segment_index"],
            ondelete="CASCADE",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    segment_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    leased_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
