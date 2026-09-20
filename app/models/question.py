from datetime import datetime, timezone
from typing import Any, List, Optional
import uuid
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    question_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True
    )
    question_text: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    question_type: Mapped[str] = mapped_column(
        String(30),
        default="unknown",
        nullable=False # 'mcq', 'true_false', 'short_answer', 'unknown'
    )
    options: Mapped[Optional[List[dict]]] = mapped_column(
        JSONB,
        nullable=True # List of dicts: [{"label": "A", "text": "..."}]
    )
    source_pages: Mapped[List[int]] = mapped_column(
        ARRAY(Integer),
        nullable=False,
        default=list # Supports multi-page questions per PRD §7
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="extracted",
        nullable=False,
        index=True # 'extracted', 'partial', 'needs_review'
    )
    review_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    document = relationship("Document", backref="questions")
    answer = relationship("Answer", back_populates="question", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Question id={self.id} num={self.question_number} type={self.question_type} status={self.status}>"
