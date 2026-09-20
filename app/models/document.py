from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    storage_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False
    )
    file_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False # 'pdf', 'jpg', 'png'
    )
    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING",
        nullable=False,
        index=True # 'PENDING', 'PROCESSING', 'COMPLETED', 'COMPLETED_WITH_WARNINGS', 'FAILED'
    )
    current_stage: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )
    total_pages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    pages_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    owner = relationship("User", backref="documents")
    group = relationship("DocumentGroup", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.original_filename} status={self.status}>"
