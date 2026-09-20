from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )
    answer_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True # Nullable per PRD §4 / §8 when answer is unknown or unmatched
    )
    answer_confidence: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False
    )
    answer_match_method: Mapped[str] = mapped_column(
        String(30),
        default="unmatched",
        nullable=False # 'number_match' | 'content_match' | 'unmatched' | 'none'
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True # Document where answer key was found (may differ from question doc per PRD §8)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    question = relationship("Question", back_populates="answer")
    source_document = relationship("Document")
