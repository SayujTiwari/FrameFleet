from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
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
