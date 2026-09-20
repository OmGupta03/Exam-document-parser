from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProcessingWarning(Base):
    __tablename__ = "processing_warnings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=True,
        index=True # Nullable for document-level warnings like "page 3 unreadable" per PRD §8
    )
    warning_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False # 'ocr_low_confidence' | 'answer_unmatched' | 'extraction_failed' | 'ambiguous_boundary'
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        default="warning",
        nullable=False # 'info' | 'warning' | 'critical'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    document = relationship("Document", backref="warnings")
    question = relationship("Question", backref="warnings")
